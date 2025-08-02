from flask import Flask, request, jsonify
from threading import Thread
from datetime import datetime, timedelta

SESSION_DATA = {}

app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

@app.route('/api/session')
def get_session():
    session_id = request.args.get("session")
    if not session_id or session_id not in SESSION_DATA:
        return jsonify({"error": "Session not found"}), 404

    data = SESSION_DATA[session_id]
    if data["expires_at"] < datetime.utcnow():
        return jsonify({"error": "Session expired"}), 410

    return jsonify({
        "user_id": data["user_id"],
        "coins": data["coins"]
    })

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
