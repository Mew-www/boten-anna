from flask import Flask, request
import csv
import os.path
import time

app = Flask(__name__)


@app.route('/')
def index():
    return 'Hello'


@app.route('/loc', methods=['POST'])
def add_known_location():
    postdata = request.form.to_dict()
    # Limb ? but multi-sensation.. Extremity ? Actor ?
    filename = 'locations_{}.txt'.format(postdata['actor'])
    is_new = False if os.path.isfile(filename) else True
    with open(filename, 'a', newline='') as fh:
        writer = csv.DictWriter(fh, delimiter=',', quotechar='"', extrasaction='ignore',
                                fieldnames=['receivetime', 'registertime', 'providername',
                                            'accuracy_m', 'lat', 'lon', 'location', 'speed_m_s'])
        if is_new:
            writer.writeheader()
        postdata['receivetime'] = int(time.time())
        writer.writerow(postdata)
    return ''
