from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route("/")
def index():
    return "Welcome to the API!"

@app.route("/data")
def get_data():
    return jsonify({"data": "here is some data"})

if __name__ == "__main__":
    app.run(debug=True)
