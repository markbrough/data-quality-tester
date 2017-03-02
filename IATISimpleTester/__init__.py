from flask import Flask
from flask_sqlalchemy import SQLAlchemy


app = Flask(__name__)

app.config.from_object('config.Config')
app.secret_key = app.config['SECRET_KEY']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

from IATISimpleTester import routes, models, views, middleware, tmpl_filters, exceptions
