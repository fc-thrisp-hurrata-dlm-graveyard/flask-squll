from __future__ import with_statement
import os
import atexit
import unittest
from datetime import datetime
import flask
from flask_squll import Squll, get_debug_queries 

def make_todo_model(db):
    class Todo(db.Model):
        __tablename__ = 'todos'
        id = db.Column('todo_id', db.Integer, primary_key=True)
        title = db.Column(db.String(60))
        text = db.Column(db.String)
        done = db.Column(db.Boolean)
        pub_date = db.Column(db.DateTime)

        def __init__(self, title, text):
            self.title = title
            self.text = text
            self.done = False
            self.pub_date = datetime.utcnow()
    return Todo

class BasicAppTestCase(unittest.TestCase):
    def setUp(self):
        app = flask.Flask(__name__)
        app.config['SQLALCHEMY_ENGINE'] = 'sqlite://'
        app.config['TESTING'] = True
        db = Squll(app)
        self.Todo = make_todo_model(db)
        @app.route('/')
        def index():
            return '\n'.join(x.title for x in self.Todo.query.all())
        @app.route('/add', methods=['POST'])
        def add():
            form = flask.request.form
            todo = self.Todo(form['title'], form['text'])
            db.session.add(todo)
            db.session.commit()
            return 'added'
        db.create_all()
        self.app = app
        self.db = db
    def tearDown(self):
        self.db.drop_all()
    def test_basic_insert(self):
        c = self.app.test_client()
        c.post('/add', data=dict(title='First Item', text='The text'))
        c.post('/add', data=dict(title='2nd Item', text='The text'))
        rv = c.get('/')
        assert rv.data == 'First Item\n2nd Item'
    def test_query_recording(self):
        with self.app.test_request_context():
            todo = self.Todo('Test 1', 'test')
            self.db.session.add(todo)
            self.db.session.commit()
            queries = get_debug_queries()
            self.assertEqual(len(queries), 1)
            query = queries[0]
            self.assert_('insert into' in query.statement.lower())
            self.assertEqual(query.parameters[0], 'Test 1')
            self.assertEqual(query.parameters[1], 'test')
            self.assert_('squll_test.py' in query.context)
            self.assert_('test_query_recording' in query.context)
    def test_helper_api(self):
        self.assertEqual(self.db.metadata, self.db.Model.metadata)

def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(BasicAppTestCase))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='suite')
