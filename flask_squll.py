from __future__ import with_statement, absolute_import

import re
import sys
from functools import wraps, partial
from math import ceil
from operator import itemgetter
from threading import Lock
from time import time

import sqlalchemy
from flask import _app_ctx_stack, abort, url_for
from flask.signals import Namespace
from sqlalchemy import orm
from sqlalchemy.engine.url import make_url
from sqlalchemy.event import listen
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy.interfaces import ConnectionProxy
from sqlalchemy.orm.exc import UnmappedClassError
from sqlalchemy.orm.session import Session


connection_stack = _app_ctx_stack

_camelcase_re = re.compile(r'([A-Z]+)(?=[a-z0-9])')

_signals = Namespace()

models_committed = _signals.signal('models-committed')
before_models_committed = _signals.signal('before-models-committed')


class _SQLAlchemyState(object):
    """Remembers configuration for the (db, app) tuple."""
    def __init__(self, db, app):
        self.db = db
        self.app = app
        self.connectors = {}


def _include_sqlalchemy(obj):
    for module in sqlalchemy, sqlalchemy.orm:
        for key in module.__all__:
            if not hasattr(obj, key):
                setattr(obj, key, getattr(module, key))
    # Note: obj.Table does not attempt to be a SQLAlchemy Table class.
    obj.Table = _make_table(obj)
    #obj.mapper = sqlalchemy.orm.mapper()#signalling_mapper \\ perhaps some addition to the mapper allowed
    obj.relationship = _wrap_with_default_query_class(obj.relationship)
    obj.relation = _wrap_with_default_query_class(obj.relation)
    obj.dynamic_loader = _wrap_with_default_query_class(obj.dynamic_loader)


def _make_table(db):
    def _make_table(*args, **kwargs):
        if len(args) > 1 and isinstance(args[1], db.Column):
            args = (args[0], db.metadata) + args[1:]
        info = kwargs.pop('info', None) or {}
        info.setdefault('bind_key', None)
        kwargs['info'] = info
        return sqlalchemy.Table(*args, **kwargs)
    return _make_table


def _set_default_query_class(d):
    if 'query_class' not in d:
        d['query_class'] = BaseQuery


def _wrap_with_default_query_class(fn):
    @wraps(fn)
    def newfn(*args, **kwargs):
        _set_default_query_class(kwargs)
        if "backref" in kwargs:
            backref = kwargs['backref']
            if isinstance(backref, basestring):
                backref = (backref, {})
            _set_default_query_class(backref[1])
        return fn(*args, **kwargs)
    return newfn


class _SignallingSession(Session):
    """"""
    def __init__(self, db, autocommit=False, autoflush=False, **options):
        self.app = db.get_app()
        self._model_changes = {}
        Session.__init__(self, autocommit=autocommit, autoflush=autoflush,
                         bind=db.engine,
                         binds=db.get_binds(self.app), **options)

    def get_bind(self, mapper, clause=None):
        # mapper is None if someone tries to just get a connection
        if mapper is not None:
            info = getattr(mapper.mapped_table, 'info', {})
            bind_key = info.get('bind_key')
            if bind_key is not None:
                state = get_state(self.app)
                return state.db.get_engine(self.app, bind=bind_key)
        return Session.get_bind(self, mapper, clause)


class _SessionSignalEvents(object):

    def register(self):
        listen(Session, 'before_commit', self.squll_before_commit)
        listen(Session, 'after_commit', self.squll_after_commit)
        listen(Session, 'after_rollback', self.squll_after_rollback)

    @staticmethod
    def squll_before_commit(session):
        d = session._model_changes
        if d:
            before_models_committed.send(session.app, changes=d.values())

    @staticmethod
    def squll_after_commit(session):
        d = session._model_changes
        if d:
            models_committed.send(session.app, changes=d.values())
            d.clear()

    @staticmethod
    def squll_after_rollback(session):
        session._model_changes.clear()


class _MapperSignalEvents(object):

    def __init__(self, mapper):
        self.mapper = mapper

    def register(self):
        listen(self.mapper, 'after_delete', self.squll_after_delete)
        listen(self.mapper, 'after_insert', self.squll_after_insert)
        listen(self.mapper, 'after_update', self.squll_after_update)

    def squll_after_delete(self, mapper, connection, target):
        self._record(mapper, target, 'delete')

    def squll_after_insert(self, mapper, connection, target):
        self._record(mapper, target, 'insert')

    def squll_after_update(self, mapper, connection, target):
        self._record(mapper, target, 'update')

    @staticmethod
    def _record(mapper, target, operation):
        pk = tuple(mapper.primary_key_from_instance(target))
        orm.object_session(target)._model_changes[pk] = (target, operation)


class _BoundDeclarativeMeta(DeclarativeMeta):

    def __new__(cls, name, bases, d):
        tablename = d.get('__tablename__')

        # generate a table name automatically if it's missing and the
        # class dictionary declares a primary key. We cannot always
        # attach a primary key to support model inheritance that does
        # not use joins. We also don't want a table name if a whole
        # table is defined
        if not tablename and d.get('__table__') is None and \
                _defines_primary_key(d):
            def _join(match):
                word = match.group()
                if len(word) > 1:
                    return ('_%s_%s' % (word[:-1], word[-1])).lower()
                return '_' + word.lower()
            d['__tablename__'] = _camelcase_re.sub(_join, name).lstrip('_')

        return DeclarativeMeta.__new__(cls, name, bases, d)

    def __init__(self, name, bases, d):
        bind_key = d.pop('__bind_key__', None)
        DeclarativeMeta.__init__(self, name, bases, d)
        if bind_key is not None:
            self.__table__.info['bind_key'] = bind_key


def get_state(app):
    assert 'sqlalchemy' in app.extensions, \
        'The sqlalchemy extension was not registered to the current ' \
        'application. Please make sure to call init_app() first.'
    return app.extensions['sqlalchemy']


class Pagination(object):

    def __init__(self, query, page, endpoint, per_page, total, items):
        self.query = query
        self.page = page
        self.endpoint = endpoint
        self.per_page = per_page
        self.total = total
        self.items = items

    def call_endpoint(self, which_page):
        if self.endpoint:
            return url_for(endpoint=self.endpoint, page=which_page)
        else:
            pass

    @property
    def pages(self):
        return int(ceil(self.total / float(self.per_page)))

    def prev(self, error_out=False):
        assert self.query is not None, 'a query object is required ' \
                                       'for this method to work'
        return self.query.paginate(self.page - 1, self.endpoint, self.per_page, error_out)

    @property
    def prev_num(self):
        return self.page - 1

    @property
    def has_prev(self):
        return self.page > 1

    def next(self, error_out=False):
        assert self.query is not None, 'a query object is required ' \
                                       'for this method to work'
        return self.query.paginate(self.page + 1, self.endpoint, self.per_page, error_out)

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def next_num(self):
        return self.page + 1

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        last = 0
        for num in xrange(1, self.pages + 1):
            if num <= left_edge or \
                (num > self.page - left_current - 1 and
                 num < self.page + right_current) or \
                    num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


class BaseQuery(orm.Query):

    def get_or_404(self, ident):
        rv = self.get(ident)
        if rv is None:
            abort(404)
        return rv

    def first_or_404(self):
        rv = self.first()
        if rv is None:
            abort(404)
        return rv

    def paginate(self, page, endpoint=None, per_page=20, error_out=True):
        if error_out and page < 1:
            abort(404)
        items = self.limit(per_page).offset((page - 1) * per_page).all()
        if not items and page != 1 and error_out:
            abort(404)
        return Pagination(self, page, endpoint, per_page, self.count(), items)


class Model(object):
    """Baseclass for custom user models."""

    #: the query class used. The :attr:`query` attribute is an instance
    #: of this class. By default a :class:`BaseQuery` is used.
    query_class = BaseQuery

    #: an instance of :attr:`query_class`. Can be used to query the
    #: database for instances of this model.
    query = None


class _EngineConnector(object):

    def __init__(self, sa, app, bind=None):
        self._sa = sa
        self._app = app
        self._engine = None
        self._connected_for = None
        self._bind = bind
        self._lock = Lock()

    def get_uri(self):
        if self._bind is None:
            return self._app.config['SQLALCHEMY_DATABASE_URI']
        binds = self._app.config.get('SQLALCHEMY_BINDS') or ()
        assert self._bind in binds, \
            'Bind %r is not specified. Set it in the SQLALCHEMY_BINDS ' \
            'configuration variable' % self._bind
        return binds[self._bind]

    def get_engine(self):
        with self._lock:
            uri = self.get_uri()
            echo = self._app.config['SQLALCHEMY_ECHO']
            if (uri, echo) == self._connected_for:
                return self._engine
            info = make_url(uri)
            options = {'convert_unicode': True}
            #self._sa.apply_pool_defaults(self._app, options)
            #self._sa.apply_driver_hacks(self._app, info, options)
            if _record_queries(self._app):
                options['proxy'] = _ConnectionDebugProxy(self._app.import_name)
            if echo:
                options['echo'] = True
            self._engine = rv = sqlalchemy.create_engine(info, **options)
            self._connected_for = (uri, echo)
            return rv


def _defines_primary_key(d):
    """Figures out if the given dictonary defines a primary key column."""
    return any(v.primary_key for k, v in d.iteritems()
               if isinstance(v, sqlalchemy.Column))


class _QueryProperty(object):
    """"""
    def __init__(self, sa):
        self.sa = sa

    def __get__(self, obj, type):
        try:
            mapper = orm.class_mapper(type)
            if mapper:
                return type.query_class(mapper, session=self.sa.session())
        except UnmappedClassError:
            return None


class Squll(object):

    def __init__(self, app=None,
                 use_native_unicode=True,
                 session_options=None):

        if session_options is None:
            session_options = {}

        session_options.setdefault(
            'scopefunc', connection_stack.__ident_func__)

        self.session = self.create_scoped_session(session_options)
        self.Model = self.make_declarative_base()
        self._engine_lock = Lock()

        if app is not None:
            self.app = app
            self.init_app(app)
        else:
            self.app = None

        _include_sqlalchemy(self)
        _MapperSignalEvents(self.mapper).register()
        _SessionSignalEvents().register()
        self.Query = BaseQuery

    @property
    def metadata(self):
        """Returns the metadata"""
        return self.Model.metadata

    def create_scoped_session(self, options=None):
        if options is None:
            options = {}
        scopefunc = options.pop('scopefunc', None)
        return orm.scoped_session(
            partial(_SignallingSession, self, **options), scopefunc=scopefunc
        )

    def make_declarative_base(self):
        base = declarative_base(cls=Model, name='Model',
                                metaclass=_BoundDeclarativeMeta)
        base.query = _QueryProperty(self)
        return base

    def init_app(self, app):
        app.config.setdefault('SQLALCHEMY_DATABASE_URI', 'sqlite://')
        app.config.setdefault('SQLALCHEMY_BINDS', None)
        app.config.setdefault('SQLALCHEMY_NATIVE_UNICODE', None)
        app.config.setdefault('SQLALCHEMY_ECHO', False)
        app.config.setdefault('SQLALCHEMY_RECORD_QUERIES', None)
        app.config.setdefault('SQLALCHEMY_POOL_SIZE', None)
        app.config.setdefault('SQLALCHEMY_POOL_TIMEOUT', None)
        app.config.setdefault('SQLALCHEMY_POOL_RECYCLE', None)

        if not hasattr(app, 'extensions'):
            app.extensions = {}
        app.extensions['sqlalchemy'] = _SQLAlchemyState(self, app)

        teardown = app.teardown_appcontext

        @teardown
        def shutdown_session(response):
            self.session.remove()
            return response

    @property
    def engine(self):
        return self.get_engine(self.get_app())

    def make_connector(self, app, bind=None):
        return _EngineConnector(self, app, bind)

    def get_engine(self, app, bind=None):
        with self._engine_lock:
            state = get_state(app)
            connector = state.connectors.get(bind)
            if connector is None:
                connector = self.make_connector(app, bind)
                state.connectors[bind] = connector
            return connector.get_engine()

    def get_app(self, reference_app=None):
        if reference_app is not None:
            return reference_app
        if self.app is not None:
            return self.app
        ctx = connection_stack.top
        if ctx is not None:
            return ctx.app
        raise RuntimeError('application not registered on db '
                           'instance and no application bound '
                           'to current context')

    def get_tables_for_bind(self, bind=None):
        """Returns a list of all tables relevant for a bind."""
        result = []
        for table in self.Model.metadata.tables.itervalues():
            if table.info.get('bind_key') == bind:
                result.append(table)
        return result

    def get_binds(self, app=None):
        """Returns a dictionary with a table->engine mapping.
        This is suitable for use of sessionmaker(binds=db.get_binds(app)).
        """
        app = self.get_app(app)
        binds = [None] + list(app.config.get('SQLALCHEMY_BINDS') or ())
        retval = {}
        for bind in binds:
            engine = self.get_engine(app, bind)
            tables = self.get_tables_for_bind(bind)
            retval.update(dict((table, engine) for table in tables))
        return retval

    def _execute_for_all_tables(self, app, bind, operation):
        app = self.get_app(app)

        if bind == '__all__':
            binds = [None] + list(app.config.get('SQLALCHEMY_BINDS') or ())
        elif isinstance(bind, basestring):
            binds = [bind]
        else:
            binds = bind

        for bind in binds:
            tables = self.get_tables_for_bind(bind)
            op = getattr(self.Model.metadata, operation)
            op(bind=self.get_engine(app, bind), tables=tables)

    def create_all(self, bind='__all__', app=None):
        self._execute_for_all_tables(app, bind, 'create_all')

    def drop_all(self, bind='__all__', app=None):
        self._execute_for_all_tables(app, bind, 'drop_all')

    def reflect(self, bind='__all__', app=None):
        self._execute_for_all_tables(app, bind, 'reflect')

    def __repr__(self):
        app = None
        if self.app is not None:
            app = self.app
        else:
            ctx = connection_stack.top
            if ctx is not None:
                app = ctx.app
        return '<%s engine=%r>' % (
            self.__class__.__name__,
            app and app.config['SQLALCHEMY_DATABASE_URI'] or None
        )

#debug\testing aid
_timer = time


def get_debug_queries():
    return getattr(connection_stack.top, 'sqlalchemy_queries', [])


def _record_queries(app):
    if app.debug:
        return True
    rq = app.config['SQLALCHEMY_RECORD_QUERIES']
    if rq is not None:
        return rq
    return bool(app.config.get('TESTING'))


class _ConnectionDebugProxy(ConnectionProxy):
    """Helps debugging the database."""

    def __init__(self, import_name):
        self.app_package = import_name

    def cursor_execute(self, execute, cursor, statement, parameters,
                       context, executemany):
        start = _timer()
        try:
            return execute(cursor, statement, parameters, context)
        finally:
            ctx = connection_stack.top
            if ctx is not None:
                queries = getattr(ctx, 'sqlalchemy_queries', None)
                if queries is None:
                    queries = []
                    setattr(ctx, 'sqlalchemy_queries', queries)
                queries.append(_DebugQueryTuple((
                    statement, parameters, start, _timer(),
                    _calling_context(self.app_package))))


class _DebugQueryTuple(tuple):
    statement = property(itemgetter(0))
    parameters = property(itemgetter(1))
    start_time = property(itemgetter(2))
    end_time = property(itemgetter(3))
    context = property(itemgetter(4))

    @property
    def duration(self):
        return self.end_time - self.start_time

    def __repr__(self):
        return '<query statement="%s" parameters=%r duration=%.03f>' % (
            self.statement,
            self.parameters,
            self.duration
        )


def _calling_context(app_path):
    frm = sys._getframe(1)
    while frm.f_back is not None:
        name = frm.f_globals.get('__name__')
        if name and (name == app_path or name.startswith(app_path + '.')):
            funcname = frm.f_code.co_name
            return '%s:%s (%s)' % (
                frm.f_code.co_filename,
                frm.f_lineno,
                funcname
            )
        frm = frm.f_back
    return '<unknown>'
