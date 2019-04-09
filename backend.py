from subprocess import check_output
from flask import Flask, request, abort, jsonify, url_for
from flask_cors import CORS
import shelve
from celery import Celery
from time import sleep
#import re

app = Flask(__name__)
# CORS(app)
CORS(app, resources={r'/*': {"origins": '*'}})
# Add redis broker to Flask app
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
# Initialize celery distributed task queue
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)


# SANITIZE_PATTERN = re.compile('[^-a-zA-Z0-9:]')

@app.route("/", defaults={'search': ''})
@app.route("/")
def main():
    search   = request.args.get('search')
    organism = request.args.get('organism')
    cell_type = request.args.get('cell_type')

    # Open or create a simple cache
    shelve_cache = shelve.open('.shelve_cache')

    # Valid URLs:
    #   '127.0.0.1:5000/'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&features'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&search=Y_581553'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&search=Y_581553&features'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&search=Hoxa1'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&search=Hoxa1&features'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&search=6:52155590-52158317'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&search=6:52155590-52158317&nearest'
    #   '127.0.0.1:5000/?organism=Mus_musculus&cell_type=Embryonic_stem_cells&search=6:52155590-52158317&expand=20000'

    # Generate the keys for the cache

    key = '|'.join([search, organism, cell_type])

    if  key not in shelve_cache:
        cmd_list = ["./search_query.R"]

        if search:
            #sanitized_search = SANITIZE_PATTERN.sub('', search.split()[0])
            sanitized_search = search.split()[0]
            cmd_list.append('--search=' + "'" + sanitized_search + "'")

        if organism:
            cmd_list.append('--organism=' + organism)

        if cell_type:
            cmd_list.append('--cell_type=' + cell_type)

        other_cmd = []
        other_cmd.append(r"sed -e '/chr/! s/\"[[:space:]]*\([[:digit:]]*\.\?[[:digit:]]\+\)\"/\1/'")
        other_cmd.append('./layout_enricher/layout_enricher')
        other_cmd.append('jq --compact-output .')

        all_cmds = " ".join(cmd_list) + " | " + " | ".join(other_cmd)

        print(all_cmds)
        try:
            output = check_output(all_cmds, shell=True, encoding='UTF-8')
            shelve_cache[key] = output
        except:
            return abort(404)
    else:
        output = shelve_cache[key]


    shelve_cache.close()

    if len(output) == 3:
        return abort(404)

    return output


@app.route("/upload_features", methods=["POST"])
def upload_features():
    print("upload_features")
    print(request.files["features"])
    features_file = request.files["features"]
    print(features_file.filename)
    print(features_file.read())
    task = processing_features.apply_async()
    return jsonify({}), 202, {'Access-Control-Expose-Headers': 'Location', 'Location': url_for('features_task', task_id=task.id)}

@celery.task(bind=True)
def processing_features(self):
    seconds = 10
    for i in range(seconds):
        sleep(i)
        self.update_state(state='PROGRESS', meta={'current': i, 'total': seconds, 'status': "processing features"})
    return {'current': seconds, 'total': seconds, 'status': 'Task completed!', 'result': 42}

@app.route('/status/<task_id>')
def features_task(task_id):
    task = processing_features.AsyncResult(task_id)
    if task.state == 'PENDING':
        # job did not start yet
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info),  # this is the exception raised
        }
    return jsonify(response)

if __name__ == "__main__":
    app.run(host='0.0.0.0')
