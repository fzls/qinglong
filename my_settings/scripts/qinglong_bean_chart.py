# 从 https://github.com/SuMaiKaDe/bot 中修改而来，主要参考以下脚本
#   jbot/bot/bean.py
#   jbot/bot/chart.py
#   jbot/bot/beandata.py

import datetime
import json
import logging
import os
import re
import time
from datetime import timedelta, timezone
from typing import Tuple, List
from urllib.parse import urlencode

import requests
import requests.adapters
from PIL import Image, ImageFont, ImageDraw
from prettytable import PrettyTable


def run_in_pycharm() -> bool:
    return os.getenv('PYCHARM_HOSTED') == '1'


# 设置logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.name = "bean_chart"
consoleHandler = logging.StreamHandler()
if run_in_pycharm():
    fmt = logging.Formatter("%(asctime)s %(funcName)s:%(lineno)-3d %(levelname)-5.5s: %(message)s")
    consoleHandler.setFormatter(fmt)
logger.addHandler(consoleHandler)

# -------- 使用说明 -------------
# 配置go-cqhttp的三个环境变量即可
# 同时须确保机器人和青龙在同一台物理机/容器上, 从而可以使用本地文件来发图片
# 将下面的 ROBOT_QL_DIR 修改为你的ql容器映射的数据目录（也就是里面有config、scripts等目录的那个目录）

# 基础配置
QL_DIR = "/ql"
# ROBOT_QL_DIR = "D:/_codes/js/qinglong/data"
ROBOT_QL_DIR = "/root/qinglong/data"
QL_API_ADDR = "http://qinglong:5700/api"
NINJA_API_ADDR = "http://localhost:5701/api"
QUICK_CHART_ADDR = "http://quickchart:3400"
if run_in_pycharm():
    QL_DIR = ROBOT_QL_DIR
    QL_API_ADDR = "http://localhost:5700/api"
    NINJA_API_ADDR = "http://localhost:5701/api"
    QUICK_CHART_ADDR = "http://localhost:5703"
    logger.warning(f"在pycharm中调试时使用本地配置 {QL_DIR} {QL_API_ADDR} {QUICK_CHART_ADDR}")

try:
    requests.get(QUICK_CHART_ADDR, timeout=1)
except:
    QUICK_CHART_ADDR = "https://quickchart.io"
    logger.info(f"未发现本地架设的quickchart服务，将使用官方服务 {QUICK_CHART_ADDR}")

FONT_FILE = f'{QL_DIR}/jbot/font/jet.ttf'
AUTH_JSON = f"{QL_DIR}/config/auth.json"
ENV_DB = f"{QL_DIR}/db/env.db"

SAVE_DIR = f"{QL_DIR}/log/.bean_chart"

GOBOT_URL = os.environ["GOBOT_URL"]
GOBOT_TOKEN = os.environ["GOBOT_TOKEN"]
GOBOT_GROUP_ID = int(os.environ["GOBOT_QQ"].split("=")[1])

logger.info(f"GO-CQHTTP CONFIG= {GOBOT_URL} {GOBOT_TOKEN} {GOBOT_GROUP_ID}")

SHA_TZ = timezone(
    timedelta(hours=8),
    name='Asia/Shanghai',
)
TIMEOUT = 10
requests.adapters.DEFAULT_RETRIES = 5
session = requests.session()
session.keep_alive = False


# 通知全部账号的京豆的统计表和图
def notify_all_account_bean_and_chart():
    message_and_image_list = []

    # 生成图和表
    logger.info("开始生成全部账号的统计图表")

    message_and_image_list.append(("京豆统计图表", ""))

    cookies = get_cks(AUTH_JSON)
    for account_idx in range_from_one(len(cookies)):
        # if account_idx != 1:
        #     message_and_image_list.append(("\n", ""))
        #
        # 账号信息
        message_and_image_list.append((get_account_name(account_idx), ""))

        # 获取豆子数据
        logger.info(f"开始获取 {get_account_name(account_idx)} 的京豆数据")
        bean_res = get_bean_data(account_idx)

        # 制作豆子统计图表
        # message_and_image_list.append(get_bean(account_idx, bean_res))
        message_and_image_list.append(get_chart(account_idx, bean_res))

        # message_and_image_list.append(("", f"{QL_DIR}/log/.bean_chart/bean_{account_idx}.jpeg"))
        # message_and_image_list.append(("", f"{QL_DIR}/log/.bean_chart/chart_{account_idx}.jpeg"))

    # 发送消息
    send_notify(message_and_image_list)


# 发送消息给cqhttp
def send_notify(message_and_image_list: List[Tuple[str, str]]):
    cq_messages = []
    for message, image in message_and_image_list:
        if message != "":
            cq_messages.append({
                "type": "text",
                "data": {
                    "text": message + "\n",
                }
            })
        if image != "":
            # 替换为机器人可以访问到的路径
            if not image.startswith(ROBOT_QL_DIR):
                image = image.replace(QL_DIR, ROBOT_QL_DIR, 1)
            cq_messages.append({
                "type": "image",
                "data": {
                    "file": f"file:///{image}",
                }
            })
            cq_messages.append({
                "type": "text",
                "data": {
                    "text": "\n",
                }
            })

    logger.info(f"开始发送消息: {cq_messages}")
    res = requests.post(f"{GOBOT_URL}?access_token={GOBOT_TOKEN}", json={
        "group_id": GOBOT_GROUP_ID,
        "message": cq_messages,
    }, timeout=100)
    logger.info(f"发送消息结果 {res.status_code} {res.text}")


def range_from_one(stop: int):
    return range(1, stop + 1)


def make_sure_dir_exists(dir_path):
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)


# 生成统计表
def get_bean(account_idx: int, res=None) -> Tuple[str, str]:
    if res is None:
        res = get_bean_data(account_idx)
    if res['code'] == 200:
        return creat_bean_count(account_idx, res['data'][3], res['data'][0], res['data'][1], res['data'][2][1:])
    else:
        return f"获取第{account_idx}个账号统计表失败", ""


# 生成统计图
def get_chart(account_idx: int, res=None) -> Tuple[str, str]:
    if res is None:
        res = get_bean_data(account_idx)
    if res['code'] == 200:
        return creat_chart(account_idx, res['data'][3], f'{get_account_name(account_idx)}',
                           res['data'][0], res['data'][1], res['data'][2][1:])
    else:
        return f"获取第{account_idx}个账号统计图失败", ""


# 获取京豆信息
def get_bean_data(i):
    try:
        cookies = get_cks(AUTH_JSON)
        if cookies:
            ck = cookies[i - 1]
            beans_res = get_beans_7days(ck)
            beantotal = get_total_beans(ck)
            if beans_res['code'] != 200:
                return beans_res
            else:
                beans_in, beans_out = [], []
                beanstotal = [int(beantotal), ]
                for i in beans_res['data'][0]:
                    beantotal = int(
                        beantotal) - int(beans_res['data'][0][i]) - int(beans_res['data'][1][i])
                    beans_in.append(int(beans_res['data'][0][i]))
                    beans_out.append(int(str(beans_res['data'][1][i]).replace('-', '')))
                    beanstotal.append(beantotal)
            return {'code': 200,
                    'data': [beans_in[::-1], beans_out[::-1], beanstotal[::-1], beans_res['data'][2][::-1]]}
    except Exception as e:
        logger.error(str(e))


# 获取cookies
def get_cks(ckfile):
    ck_reg = re.compile(r'pt_key=\S*?;.*?pt_pin=\S*?;')

    with open(ckfile, 'r', encoding='utf-8') as f:
        auth = json.load(f)
    lines = str(env_manage_QL('search', 'JD_COOKIE', auth['token']))

    cookies = ck_reg.findall(lines)
    for ck in cookies:
        if ck == 'pt_key=xxxxxxxxxx;pt_pin=xxxx;':
            cookies.remove(ck)
            break
    return cookies


user_pt_pin_to_nickname = {}


def update_user_nicknames():
    with open(ENV_DB, 'r', encoding='utf-8') as f:
        envs = f.readlines()

    for env_json in envs:
        env = json.loads(env_json)
        if env['name'] != "JD_COOKIE":
            continue

        cookie = env['value']
        pt_pin = parse_pt_pin(cookie)

        # 先使用pt_pin
        nickname = pt_pin
        if 'remarks' in env:
            # 如果有备注，则使用备注
            nickname = env['remarks']

            # 如果备注中有remark=字样
            for remark in env['remarks'].split(';'):
                if remark == "" or '=' not in remark:
                    continue

                k, v = remark.split('=')
                if k != "remark":
                    continue

                nickname = v
                break

        user_pt_pin_to_nickname[pt_pin] = nickname


def get_account_name(account_idx: int) -> str:
    if len(user_pt_pin_to_nickname) == 0:
        update_user_nicknames()

    cookies = get_cks(AUTH_JSON)
    if len(cookies) != 0:
        ck = cookies[account_idx - 1]
        pt_pin = parse_pt_pin(ck)

        if pt_pin != "" and pt_pin in user_pt_pin_to_nickname:
            nickname = user_pt_pin_to_nickname[pt_pin]
            return f"{account_idx} - {nickname}"

    return f"{account_idx}"


def parse_pt_pin(cookie: str) -> str:
    pt_pin = ""
    for kv in cookie.split(';'):
        if 'pt_pin' in kv:
            pt_pin = kv.split('=')[1]
            break

    return pt_pin


def env_manage_QL(fun, envdata, token):
    url = f'{QL_API_ADDR}/envs'
    headers = {
        'Authorization': f'Bearer {token}'
    }
    try:
        if fun == 'search':
            params = {
                't': int(round(time.time() * 1000)),
                'searchValue': envdata
            }
            res = requests.get(url, params=params, headers=headers).json()
        elif fun == 'add':
            data = {
                'name': envdata['name'],
                'value': envdata['value'],
                'remarks': envdata['remarks'] if 'remarks' in envdata.keys() else ''
            }
            res = requests.post(url, json=[data], headers=headers).json()
        elif fun == 'edit':
            data = {
                'name': envdata['name'],
                'value': envdata['value'],
                '_id': envdata['_id'],
                'remarks': envdata['remarks'] if 'remarks' in envdata.keys() else ''
            }
            res = requests.put(url, json=data, headers=headers).json()
        elif fun == 'disable':
            data = [envdata['_id']]
            res = requests.put(url + '/disable', json=data,
                               headers=headers).json()
        elif fun == 'enable':
            data = [envdata['_id']]
            res = requests.put(url + '/enable', json=data,
                               headers=headers).json()
        elif fun == 'del':
            data = [envdata['_id']]
            res = requests.delete(url, json=data, headers=headers).json()
        else:
            res = {'code': 400, 'data': '未知功能'}
    except Exception as e:
        res = {'code': 400, 'data': str(e)}
    finally:
        return res


def get_beans_7days(ck):
    try:
        day_7 = True
        page = 0
        headers = {
            "Host": "api.m.jd.com",
            "Connection": "keep-alive",
            "charset": "utf-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; MI 9 Build/QKQ1.190825.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.62 XWEB/2797 MMWEBSDK/201201 Mobile Safari/537.36 MMWEBID/7986 MicroMessenger/8.0.1840(0x2800003B) Process/appbrand4 WeChat/arm64 Weixin NetType/4G Language/zh_CN ABI/arm64 MiniProgramEnv/android",
            "Content-Type": "application/x-www-form-urlencoded;",
            "Accept-Encoding": "gzip, compress, deflate, br",
            "Cookie": ck,
            "Referer": "https://servicewechat.com/wxa5bf5ee667d91626/141/page-frame.html",
        }
        days = []
        for i in range(0, 7):
            days.append(
                (datetime.date.today() - datetime.timedelta(days=i)).strftime("%Y-%m-%d"))
        beans_in = {key: 0 for key in days}
        beans_out = {key: 0 for key in days}
        while day_7:
            page = page + 1
            resp = session.get("https://api.m.jd.com/api", params=gen_params(page),
                               headers=headers, timeout=TIMEOUT).text
            res = json.loads(resp)
            if res['resultCode'] == 0:
                if len(res['data']['list']) == 0:
                    day_7 = False
                    break

                for i in res['data']['list']:
                    for date in days:
                        if str(date) in i['createDate'] and i['amount'] > 0:
                            beans_in[str(date)] = beans_in[str(
                                date)] + i['amount']
                            break
                        elif str(date) in i['createDate'] and i['amount'] < 0:
                            beans_out[str(date)] = beans_out[str(
                                date)] + i['amount']
                            break
                    if i['createDate'].split(' ')[0] not in str(days):
                        day_7 = False
            else:
                return {'code': 400, 'data': res}
        return {'code': 200, 'data': [beans_in, beans_out, days]}
    except Exception as e:
        logger.error(str(e))
        return {'code': 400, 'data': str(e)}


def gen_params(page):
    body = gen_body(page)
    params = {
        "functionId": "jposTradeQuery",
        "appid": "swat_miniprogram",
        "client": "tjj_m",
        "sdkName": "orderDetail",
        "sdkVersion": "1.0.0",
        "clientVersion": "3.1.3",
        "timestamp": int(round(time.time() * 1000)),
        "body": json.dumps(body)
    }
    return params


def gen_body(page):
    body = {
        "beginDate": datetime.datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(SHA_TZ).strftime(
            "%Y-%m-%d %H:%M:%S"),
        "endDate": datetime.datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(SHA_TZ).strftime(
            "%Y-%m-%d %H:%M:%S"),
        "pageNo": page,
        "pageSize": 20,
    }
    return body


def get_total_beans(ck):
    try:
        headers = {
            "Host": "wxapp.m.jd.com",
            "Connection": "keep-alive",
            "charset": "utf-8",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; MI 9 Build/QKQ1.190825.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.62 XWEB/2797 MMWEBSDK/201201 Mobile Safari/537.36 MMWEBID/7986 MicroMessenger/8.0.1840(0x2800003B) Process/appbrand4 WeChat/arm64 Weixin NetType/4G Language/zh_CN ABI/arm64 MiniProgramEnv/android",
            "Content-Type": "application/x-www-form-urlencoded;",
            "Accept-Encoding": "gzip, compress, deflate, br",
            "Cookie": ck,
        }
        jurl = "https://wxapp.m.jd.com/kwxhome/myJd/home.json"
        resp = session.get(jurl, headers=headers, timeout=TIMEOUT).text
        res = json.loads(resp)
        return res['user']['jingBean']
    except Exception as e:
        logger.error(str(e))


def creat_bean_count(account_idx, date, beansin, beansout, beanstotal) -> Tuple[str, str]:
    tb = PrettyTable()
    tb.add_column('DATE', date)
    tb.add_column('BEANSIN', beansin)
    tb.add_column('BEANSOUT', beansout)
    tb.add_column('TOTAL', beanstotal)
    font = ImageFont.truetype(FONT_FILE, 18)
    im = Image.new("RGB", (500, 260), (244, 244, 244))
    dr = ImageDraw.Draw(im)
    dr.text((10, 5), str(tb), font=font, fill="#000000")

    make_sure_dir_exists(SAVE_DIR)
    save_path = f"{SAVE_DIR}/bean_{account_idx}.jpeg"
    im.save(save_path)
    logger.info(f'您的账号 {get_account_name(account_idx)} 收支情况 统计表格 已保存到 {save_path}')

    return "", os.path.realpath(save_path)


def creat_chart(account_idx, xdata, title, bardata, bardata2, linedate):
    qc = QuickChart()
    qc.background_color = '#fff'
    qc.width = "1000"
    qc.height = "600"
    qc.config = {
        "type": "bar",
        "data": {
            "labels": xdata,
            "datasets": [
                {
                    "label": "IN",
                    "backgroundColor": [
                        "rgb(255, 99, 132)",
                        "rgb(255, 159, 64)",
                        "rgb(255, 205, 86)",
                        "rgb(75, 192, 192)",
                        "rgb(54, 162, 235)",
                        "rgb(153, 102, 255)",
                        "rgb(255, 99, 132)"
                    ],
                    "yAxisID": "y1",
                    "data": bardata
                },
                {
                    "label": "OUT",
                    "backgroundColor": [
                        "rgb(255, 99, 132)",
                        "rgb(255, 159, 64)",
                        "rgb(255, 205, 86)",
                        "rgb(75, 192, 192)",
                        "rgb(54, 162, 235)",
                        "rgb(153, 102, 255)",
                        "rgb(255, 99, 132)"
                    ],
                    "yAxisID": "y1",
                    "data": bardata2
                },
                {
                    "label": "TOTAL",
                    "type": "line",
                    "fill": False,
                    "backgroundColor": "rgb(201, 203, 207)",
                    "yAxisID": "y2",
                    "data": linedate
                }
            ]
        },
        "options": {
            "plugins": {
                "datalabels": {
                    "anchor": 'end',
                    "align": -100,
                    "color": '#666',
                    "font": {
                        "size": 20,
                    }
                },
            },
            "legend": {
                "labels": {
                    "fontSize": 20,
                    "fontStyle": 'bold',
                }
            },
            "title": {
                "display": True,
                "text": f'{title}   收支情况',
                "fontSize": 24,
            },
            "scales": {
                "xAxes": [{
                    "ticks": {
                        "fontSize": 24,
                    }
                }],
                "yAxes": [
                    {
                        "id": "y1",
                        "type": "linear",
                        "display": False,
                        "position": "left",
                        "ticks": {
                            "max": int(int(max([max(bardata), max(bardata2)]) + 100) * 2)
                        },
                        "scaleLabel": {
                            "fontSize": 20,
                            "fontStyle": 'bold',
                        }
                    },
                    {
                        "id": "y2",
                        "type": "linear",
                        "display": False,
                        "ticks": {
                            "min": int(min(linedate) * 2 - (max(linedate)) - 100),
                            "max": int(int(max(linedate)))
                        },
                        "position": "right"
                    }
                ]
            }
        }
    }

    make_sure_dir_exists(SAVE_DIR)
    save_path = f"{SAVE_DIR}/chart_{account_idx}.jpeg"
    qc.to_file(save_path)
    logger.info(f'您的账号 {get_account_name(account_idx)} 收支情况 统计图 已保存到 {save_path}')

    return "", os.path.realpath(save_path)


class QuickChart:
    def __init__(self):
        self.config = None
        self.width = 500
        self.height = 300
        self.background_color = '#ffffff'
        self.device_pixel_ratio = 1.0
        self.format = 'png'
        self.version = '2.9.4'
        self.key = None
        # self.scheme = 'https'
        # self.host = 'quickchart.io'

    def is_valid(self):
        return self.config is not None

    def get_url_base(self):
        return QUICK_CHART_ADDR

    def get_url(self):
        if not self.is_valid():
            raise RuntimeError(
                'You must set the `config` attribute before generating a url')
        params = {
            'c': dump_json(self.config) if type(self.config) == dict else self.config,
            'w': self.width,
            'h': self.height,
            'bkg': self.background_color,
            'devicePixelRatio': self.device_pixel_ratio,
            'f': self.format,
            'v': self.version,
        }
        if self.key:
            params['key'] = self.key
        return '%s/chart?%s' % (self.get_url_base(), urlencode(params))

    def _post(self, url):
        try:
            import requests
        except:
            raise RuntimeError('Could not find `requests` dependency')

        postdata = {
            'chart': dump_json(self.config) if type(self.config) == dict else self.config,
            'width': self.width,
            'height': self.height,
            'backgroundColor': self.background_color,
            'devicePixelRatio': self.device_pixel_ratio,
            'format': self.format,
            'version': self.version,
        }
        if self.key:
            postdata['key'] = self.key
        st = time.time()
        resp = requests.post(url, json=postdata)
        if resp.status_code != 200:
            raise RuntimeError(
                'Invalid response code from chart creation endpoint')
        return resp

    def get_short_url(self):
        resp = self._post('%s/chart/create' % self.get_url_base())
        parsed = json.loads(resp.text)
        if not parsed['success']:
            raise RuntimeError(
                'Failure response status from chart creation endpoint')
        return parsed['url']

    def get_bytes(self):
        resp = self._post('%s/chart' % self.get_url_base())
        return resp.content

    def to_file(self, path):
        content = self.get_bytes()
        with open(path, 'wb') as f:
            f.write(content)


FUNCTION_DELIMITER_RE = re.compile('\"__BEGINFUNCTION__(.*?)__ENDFUNCTION__\"')


class QuickChartFunction:
    def __init__(self, script):
        self.script = script

    def __repr__(self):
        return self.script


def serialize(obj):
    if isinstance(obj, QuickChartFunction):
        return '__BEGINFUNCTION__' + obj.script + '__ENDFUNCTION__'
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj.__dict__


def dump_json(obj):
    ret = json.dumps(obj, default=serialize, separators=(',', ':'))
    ret = FUNCTION_DELIMITER_RE.sub(
        lambda match: json.loads('"' + match.group(1) + '"'), ret)
    return ret


def demo():
    idx = 1
    get_bean(idx)
    get_chart(idx)


if __name__ == '__main__':
    # demo()
    # get_account_name(1)

    notify_all_account_bean_and_chart()
