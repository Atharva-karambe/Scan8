from flask import Flask, render_template, request, redirect, url_for, Response
from datetime import datetime
from werkzeug.utils import secure_filename
import os
import shortuuid
from pymongo import MongoClient
import json
import validators
from hurry.filesize import size, si
from dotenv import load_dotenv
from flask_socketio import SocketIO
from flask_cors import CORS
from redis import Redis
from threading import Thread

load_dotenv()

app = Flask(__name__)
upload_path = os.getenv("UPLOAD_DIRECTORY")
result_path = os.getenv("RESULTS_PATH")
CORS(app,resources={r"/*":{"origins":"*"}})
socketio = SocketIO(app, message_queue=os.environ.get('REDIS_URL'),cors_allowed_origins='*')


app.config['UPLOAD_FOLDER'] = upload_path

mongodbHost = os.getenv("MONGODB_HOST")
mongodbPort = int(os.getenv("MONGODB_PORT"))

client = MongoClient(mongodbHost, mongodbPort)
scan8 = client['scan8']
links = scan8['links']
runninglinks = scan8['runninglinks']
prequeuedScans = scan8['prequeuedScans']
queuedScans = scan8['queuedScans']
runningScans = scan8['runningScans']
completedScans = scan8['completedScans']

#create common/Results and Uploods if not there
if not os.path.exists(upload_path):
    os.makedirs(upload_path)
if not os.path.exists(result_path):
    os.makedirs(result_path)

redis_client = Redis(host=os.getenv('REDIS_HOST'),port=int(os.getenv("REDIS_PORT")))
redis_pubsub = redis_client.pubsub()
redis_pubsub.subscribe('scan_progress')

# Socket implementation
def background_thread():

    def parse_message(message):
        json_str = message.decode('utf-8')
        return json.loads(json_str)

    for message in redis_pubsub.listen():
        if message['type'] == 'message':
            json_data = parse_message(message['data'])
            socketio.emit('update', {'data': json_data})

@socketio.on('connect')
def connect():
    print("Started background thread")
    thread = Thread(target=background_thread)
    thread.daemon = True
    thread.start()

def index():
    prequeued = prequeuedScans.find()
    queued = queuedScans.find()
    running = runningScans.find()
    completed = completedScans.find()
    runninglink = runninglinks.find()
    return render_template('index.html', prequeued=prequeued, queued=queued, running=running, completed=completed, runninglink=list(runninglink))

def upload_files():
    if request.method == 'POST':
        id = shortuuid.uuid()
        uploadedFiles = request.files.getlist('dir')
        dirPath = os.path.join(app.config['UPLOAD_FOLDER'], str(id))
        os.mkdir(dirPath)

        for file in uploadedFiles:
            if file:
                filename = secure_filename(file.filename)
                file.save(os.path.join(dirPath, filename ))

        curTime = datetime.now()
        dirSize = 0
        numFiles = 0
        for element in os.scandir(dirPath):
            dirSize+=os.path.getsize(element)
            numFiles += 1
            
        scan8.prequeuedScans.insert_one(
            {"_id": str(id), "submitTime": {"date": curTime.strftime("%d-%m-%Y"), "time": curTime.strftime(
                "%H:%M:%S")}, "size": size(dirSize, system=si), "files": {"total": numFiles, "completed": 0}, "result": {"Virus": 0, "Virus_name": []}}
        )

    return redirect(url_for('dashboard'))

def link():
    if request.method == 'POST':
    	try:
    		id = shortuuid.uuid()
    		link = request.form.get('link')
    		proxy = request.form.get('proxy')
    		if not validators.url(link):
    			raise InvalidURLException("Invalid URL")
    		scan8.links.insert_one({"_id": str(id), "link": link, "proxy": proxy})
    		return "ok"
    	except:
    		return "error"

def progress():
    def generate():
        while True:
            running = runningScans.find()
            x = {}
            for item in running:
                x[item["_id"]] = str(
                    (item["files"]["completed"] / item["files"]["total"]) * 100)

            yield "data:" + json.dumps(x) + "\n\n"

    return Response(generate(), mimetype='text/event-stream')


app.add_url_rule("/", endpoint="dashboard", view_func=index, methods=['GET'])
app.add_url_rule("/progress", endpoint="progress",
                 view_func=progress, methods=['GET'])
app.add_url_rule("/upload", endpoint="upload",
                 view_func=upload_files, methods=['GET', 'POST'])
app.add_url_rule("/link", endpoint="link",
                 view_func=link, methods=['GET', 'POST'])

if __name__ == "__main__":
    app.debug = True
    socketio.run(app, log_output=True)
   
