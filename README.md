This is a 'downstream' version of flask-sqlalchemy that removes legacy code servicing Flask versions < 0.9 and Sqlalchemy versions < 0.7.

To install the latest version:

    pip install flask-squll

Use is paralell to usage of flask-sqlalchemy, using 'squll' and 'Squll' respectively.

Currently, flask signals do not work, plans pending are to integrate that with the newer event system. See tests for complete coverage of what should work and what should not, where at this time signals & minor other issue with relations are noted. All other tests are clean.
