from flask_cors import CORS
from funasr import AutoModel
from flask import Flask, request, render_template, jsonify, send_from_directory
import os
import logging
import time
from logging.handlers import RotatingFileHandler
import warnings

warnings.filterwarnings('ignore')
import threading
from waitress import serve
import lib
from lib import cfg, tool
from lib.cfg import ROOT_DIR
# 配置日志
# 禁用 Werkzeug 默认的日志处理器
log = logging.getLogger('werkzeug')
log.handlers[:] = []
log.setLevel(logging.WARNING)
app = Flask(__name__, static_folder=os.path.join(ROOT_DIR, 'static'), static_url_path='/static',
            template_folder=os.path.join(ROOT_DIR, 'templates'))
root_log = logging.getLogger()  # Flask的根日志记录器
CORS(app)
root_log.handlers = []
root_log.setLevel(logging.WARNING)

# 输出到 stdout 和 stderr
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.WARNING)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
stream_handler.setFormatter(formatter)
app.logger.addHandler(stream_handler)

logging.info("system start")

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(app.config['STATIC_FOLDER'], filename)


@app.route('/')
def index():
    return render_template("index.html",
                           version=lib.version_str,
                           web_address=cfg.web_address,
                           root_dir=ROOT_DIR.replace('\\', '/'))


@app.route('/api', methods=['GET', 'POST'])
def api():
    try:
        # 获取上传的文件
        audio_file = request.files['audio']
        # 如果是mp4
        noextname, ext = os.path.splitext(audio_file.filename)
        ext = ext.lower()
        # 如果是视频，先分离
        wav_file = os.path.join(cfg.TMP_DIR, f'{time.time()}.wav')
        print(f'{wav_file=}')
        if not os.path.exists(wav_file) or os.path.getsize(wav_file) == 0:
            if ext in ['.mp4', '.mov', '.avi', '.mkv', '.mpeg', '.mp3', '.flac']:
                video_file = os.path.join(cfg.TMP_DIR, f'{noextname}{ext}')
                audio_file.save(video_file)
                params = [
                    "-i",
                    video_file,
                ]
                if ext not in ['.mp3', '.flac']:
                    params.append('-vn')
                params.append(wav_file)
                rs = tool.runffmpeg(params)
                if rs != 'ok':
                    return jsonify({"code": 1, "msg": "预处理输入为wav时失败"})
            elif ext == '.wav':
                audio_file.save(wav_file)
            else:
                return jsonify({"code": 1, "msg": f"不支持的格式 {ext}"})
        #print(f'{ext=}')
        sets = cfg.parse_ini()
        model = AutoModel(model="paraformer-zh", model_revision="v2.0.4",
                          vad_model="fsmn-vad", vad_model_revision="v2.0.4",
                          punc_model="ct-punc-c", punc_model_revision="v2.0.4",
                          local_files_only=cfg.sets.get('only_local',False)
                          )
        res = model.generate(input=wav_file, return_raw_text=True, is_final=True,
                             sentence_timestamp=True, batch_size_s=100)
        raw_subtitles = []
        for it in res[0]['sentence_info']:
            #print(it)
            raw_subtitles.append({
                "line": len(raw_subtitles) + 1,
                "text": it['text'],
                "start_time": it['start'],
                "end_time": it['end'],
                "time": f'{tool.ms_to_time_string(ms=it["start"])} --> {tool.ms_to_time_string(ms=it["end"])}'
            })

        return jsonify({"code": 0, "msg": 'ok', "data": raw_subtitles})
    except Exception as e:
        print(e)
        app.logger.error(f'[api]error: {e}')
        return jsonify({'code': 2, 'msg': str(e)})


if __name__ == '__main__':
    http_server = None
    try:
        host = cfg.web_address.split(':')
        logging.info(f'url=http://{cfg.web_address}')
        threading.Thread(target=tool.openweb, args=(cfg.web_address,)).start()
        logging.info('启动成功')
        serve(app, host=host[0], port=int(host[1]))
    except Exception as e:
        logging.error("error:" + str(e))
        app.logger.error(f"[app]start error:{str(e)}")
