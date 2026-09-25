from flask_wtf import FlaskForm
from wtforms import IntegerField, PasswordField, StringField, TextAreaField
from wtforms.validators import DataRequired, EqualTo, Length, NumberRange, Optional


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])


class RegisterForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm = PasswordField(
        "Confirm password", validators=[DataRequired(), EqualTo("password", "Passwords must match.")]
    )


class BookForm(FlaskForm):
    isbn = StringField("ISBN", validators=[DataRequired(), Length(max=20)])
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    author = StringField("Author", validators=[DataRequired(), Length(max=255)])
    genre = StringField("Genre", validators=[DataRequired(), Length(max=80)])
    year = IntegerField("Year", validators=[Optional(), NumberRange(min=0, max=2100)])
    copies_total = IntegerField("Copies", default=1, validators=[NumberRange(min=0, max=100)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=5000)])


class ActionForm(FlaskForm):
    """Empty form used for CSRF-protected POST buttons."""
