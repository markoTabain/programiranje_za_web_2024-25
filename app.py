from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_bootstrap import Bootstrap5
from pymongo import MongoClient
from bson.objectid import ObjectId

import gridfs
import markdown

from flask_login import UserMixin, LoginManager
from flask_login import login_required, current_user, login_user, logout_user
from forms import BlogPostForm, LoginForm, RegisterForm, NameForm, ProfileForm
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Mail, Message

from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
bootstrap = Bootstrap5(app)

app.secret_key = os.getenv('SECRET_KEY')

# Konfiguracija Flask-Mail-a
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

client = MongoClient("mongodb://localhost:27017/")
db = client["pzw_blog_database"]
posts_collection = db["posts"]
fs = gridfs.GridFS(db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

mail = Mail(app)

def send_confirmation_email(user_email):
    try:
        token = generate_confirmation_token(user_email)
        confirm_url = url_for('confirm_email', token=token, _external=True)
        html = render_template(
            'email_confirmation.html',
            confirm_url=confirm_url,
            user_email=user_email,
            current_year=datetime.now().year
        )
        subject = "Molimo potvrdite email adresu"
        msg = Message(subject, recipients=[user_email], html=html)
        mail.send(msg)
        print("Email poslan!")
    except Exception as e:
        print("Greška pri slanju maila", repr(e))
        raise

users_collection = db['users']

def generate_confirmation_token(email):
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='email-confirmation-salt')

def confirm_token(token, expiration=3600):  # Token expires in 1 hour
    serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='email-confirmation-salt', max_age=expiration)
    except:
        return False
    return email

@app.route('/test-email')
def test_email():
    try:
        msg = Message("Test mail", recipients=["markotabain745@gmail.com"], body="Ovo je test poruka.")
        mail.send(msg)
        return "Email poslan!"
    except Exception as e:
        return f"Greška: {e}"

@login_manager.user_loader
def load_user(email):
    user_data = users_collection.find_one({"email": email})
    if user_data:
        return User(user_data['email'])
    return None

@login_manager.user_loader
def load_user(email):
    user_data = users_collection.find_one({"email": email})
    if user_data:
        return User(user_data['email'])
    return None

class User(UserMixin):
    def __init__(self, email):
        self.id = email

    @classmethod
    def get(self_class, id):
        try:
            return self_class(id)
        except UserNotFoundError:
            return None

class UserNotFoundError(Exception):
    pass


from werkzeug.security import generate_password_hash, check_password_hash

users_collection = db['users']

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        email = request.form['email']
        password = request.form['password']
        existing_user = users_collection.find_one({"email": email})

        if existing_user:
            flash('Korisnik već postoji', category='error')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        users_collection.insert_one({
            "email": email,
            "password": hashed_password,
            "is_confirmed": False
        })

        send_confirmation_email(email)
        flash('Registracija uspješna. Sad se možete prijaviti', category='success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)



@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = confirm_token(token)
    except:
        flash('Link za potvrdu je neisprava ili je istekao.', 'danger')
        return redirect(url_for('unconfirmed'))

    user = users_collection.find_one({'email': email})
    if user['is_confirmed']:
        flash('Vaš račun je već potvrđen. Molimo prijavite se.', 'success')
    else:
        users_collection.update_one({'email': email}, {'$set': {'is_confirmed': True}})
        flash('Vaš račun je potvrđen. Hvala! Molimo prijavite se.', 'success')
    
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = request.form['email']
        password = request.form['password']
        user_data = users_collection.find_one({"email": email})

        if user_data is not None and check_password_hash(user_data['password'], password):

            # 🔒 Provjera potvrde e-maila
            if not user_data.get('is_confirmed', False):
                flash('Molimo potvrdite vašu e-mail adresu prije prijave.', category='warning')
                return redirect(url_for('login'))

            user = User(user_data['email'])
            login_user(user, form.remember_me.data)

            next = request.args.get('next')
            if next is None or not next.startswith('/'):
                next = url_for('index')
            flash('Uspješno ste se prijavili!', category='success')
            return redirect(next)

        flash('Neispravno korisničko ime ili zaporka!', category='warning')

    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Odjavili ste se.', category='success')
    return redirect(url_for('index'))


@app.route("/", methods=["GET", "POST"])
def index():
    form = NameForm()
    if form.validate_on_submit():
        old_name = session.get("name")
        new_name = form.name.data
        if old_name and old_name != new_name:
            flash("Promijenili ste ime!", "success")

        session["name"] = new_name
        session.modified = True
        return redirect(url_for("index"))
    
    published_posts = posts_collection.find({"status": "published"}).sort('date', -1)

    return render_template("index.html", name = session.get("name"), form=form, posts=published_posts)

@app.route('/blog/create', methods=["GET", "POST"])
@login_required
def post_create():
    form = BlogPostForm()
    if form.validate_on_submit():
        image_id = save_image_to_gridfs(request, fs) or None  # Osiguraj da je `None` ako nema slike
        post = {
            'title': form.title.data,
            'content': form.content.data,
            'author': current_user.get_id(),
            'status': form.status.data,
            'date': datetime.combine(form.date.data, datetime.min.time()),
            'tags': form.tags.data,
            'image_id': image_id,
            'date_created': datetime.utcnow()
        }
        posts_collection.insert_one(post)
        flash('Članak je uspješno upisan.', 'success')
        return redirect(url_for('index'))
    return render_template('blog_edit.html', form=form)

@app.route('/blog/<post_id>')
def post_view(post_id=None):
    post = posts_collection.find_one({'_id': ObjectId(post_id)})

    if not post:
        flash("Članak nije pronađen!", "danger")
        return redirect(url_for('index'))

    return render_template('blog_view.html', post=post)

@app.route('/blog/edit/<post_id>', methods=["GET", "POST"])
def post_edit(post_id):
    form = BlogPostForm()
    post = posts_collection.find_one({"_id": ObjectId(post_id)})

    if request.method == 'GET':
        form.title.data = post['title']
        form.content.data = post['content']
        form.date.data = post['date']
        form.tags.data = post['tags']
        form.status.data = post['status']
    elif form.validate_on_submit():
        posts_collection.update_one(
            {"_id": ObjectId(post_id)},
            {"$set": {
                'title': form.title.data,
                'content': form.content.data,
                'date': datetime.combine(form.date.data, datetime.min.time()),
                'tags': form.tags.data,
                'status': form.status.data,
                'date_updated': datetime.utcnow()
            }}
        )
        image_id = save_image_to_gridfs(request, fs)
        if image_id is not None:
            posts_collection.update_one(
                {"_id": ObjectId(post_id)},
                {"$set": {
                    'image_id': image_id,
                }}
        )
        flash('Članak je uspješno ažuriran.', 'success')
        return redirect(url_for('post_view', post_id = post_id))
    else:
        flash('Dogodila se greška!', category='warning')
    return render_template('blog_edit.html', form=form)

@app.route('/blog/delete/<post_id>', methods=['POST'])
def delete_post(post_id):
    posts_collection.delete_one({"_id": ObjectId(post_id)})
    flash('Članak je uspješno obrisan.', 'success')
    return redirect(url_for('index'))

def save_image_to_gridfs(request, fs):
    image_id = None
    if 'image' in request.files:
        image = request.files['image']
        if image.filename != '':
            image_id = fs.put(image, filename=image.filename)
        else:
            image_id = None
    else:
        image_id = None
    return image_id

@app.route('/image/<image_id>')
def serve_image(image_id):
    image = fs.get(ObjectId(image_id))
    return image.read(), 200, {'Content-Type': 'image/jpeg'}

@app.template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(obj=current_user)  # Pre-fill form with current user's data
    user_data = users_collection.find_one({"email": current_user.get_id()})

    if request.method == 'GET':
        form.first_name.data = user_data.get("first_name", "")
        form.last_name.data = user_data.get("last_name", "")
        form.bio.data = user_data.get("bio", "")
    
    elif form.validate_on_submit():
        users_collection.update_one(
            {"email": current_user.get_id()},
            {"$set": {
                "first_name": form.first_name.data,
                "last_name": form.last_name.data,
                "bio": form.bio.data
            }}
        )
        if form.image.data:
            # Pobrišimo postojeću ako postoji
            if hasattr(user_data, 'image_id') and user_data.image_id:
                fs.delete(user_data.image_id)
            
            image_id = save_image_to_gridfs(request, fs)
            if image_id != None:
                users_collection.update_one(
                {"_id": user_data['_id']},
                {"$set": {
                    'image_id': image_id,
                }}
            )

        flash("Profil ažuriran.", "success")
        return redirect(url_for('profile'))

    return render_template('profile.html', form=form, image_id=user_data.get("image_id"))

@app.route("/myposts")
def my_posts():
    posts = posts_collection.find({"author": current_user.get_id()}).sort("date", -1)
    return render_template('my_posts.html', posts = posts)
