from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_cors import CORS
from llm import ask_dndsy
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management
CORS(app)

PASSWORD = "dndsy"  # Your specified password

def check_auth():
    return session.get('authenticated', False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('home'))
        return render_template('login.html', error="Incorrect password")
    return render_template('login.html', error=None)

@app.route('/')
def home():
    if not check_auth():
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    if not check_auth():
        return jsonify({'error': 'Unauthorized'}), 401
        
    data = request.json
    user_message = data.get('message', '')
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    try:
        response = ask_dndsy(user_message)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5001))) 