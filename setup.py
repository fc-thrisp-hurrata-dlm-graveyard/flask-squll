"""
Flask-Squll
-------------

A flask/sqlalchemy integration based on flask-sqlalchemy
"""
from setuptools import setup

setup(
    name='Flask-Squll',
    version='0.2',
    url='https://github.com/thrisp/flask-squll',
    license='BSD',
    author='hurrata/thrisp',
    author_email='blueblank@example.com',
    description='flask + sqlalchemy integration minus legacy for older versions of flask(<0.9)/sqlalchemy(<0.7)',
    long_description=__doc__,
    py_modules=['flask_squll'],
    # if you would be using a package instead use packages instead
    # of py_modules:
    # packages=['flask_sqlite3'],
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=[
        'setuptools',
        'Flask >= 0.9',
        'SQLAlchemy >= 0.7'
    ],
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ]
)
