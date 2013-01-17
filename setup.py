"""
Flask-Squll
-------------

A flask/sqlalchemy integration based on flask-sqlalchemy
"""
from setuptools import setup

setup(
    name='Flask-Squll',
    version='0.0',
    url='http://tbd/flask-squll/',
    license='BSD',
    author='Your Name',
    author_email='your-email@example.com',
    description='flask + sqlalchemy integration',
    long_description=__doc__,
    py_modules=['flask_squll'],
    # if you would be using a package instead use packages instead
    # of py_modules:
    # packages=['flask_sqlite3'],
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=[
        'Flask'
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
