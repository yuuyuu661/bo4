from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

SESSION_DATA = {}  # 外部から import されるように定義

@app.route("/")
def home():
    return "✅ Slot Bot Flask サーバー稼働中"

@app.route("/api/session")
def check_session():
    session_id = request.args.get("session")
    if not session_id or session_id not in SESSION_DATA:
        return jsonify({"valid": False}), 404

    session = SESSION_DATA[session_id]
    if datetime.utcnow() > session["expires_at"]:
        return jsonify({"valid": False, "reason": "expired"}), 410

    return jsonify({
        "valid": True,
        "coins": session["coins"],
        "user_id": session["user_id"]
    })

def keep_alive():
    from threading import Thread
    def run():
        app.run(host="0.0.0.0", port=8080)
    Thread(target=run).start()
