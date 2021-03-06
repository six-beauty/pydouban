# -*- coding: utf-8 -*-

import requests
import requests.utils
import pickle
import codecs
import re
import os
import random
import logging
import logging.handlers
import time
import bs4 
import turibot
import redis
import queue
import urllib
import json
import traceback
import threading
import captcha
import correct
from lxml import etree

#send_mail
import smtplib  
import email.mime.multipart  
import email.mime.text  
import email.utils

# 1. 启动机器人前，需要把验证码处理网站也打开,就是绑定了 http://47.98.177.0:9903/ 那个进程。 
    #目录：/home/hero/git_cousin/cousin/captcha， 执行run.sh (crontab 里面有配置，会定时执行，预防它挂掉)


# 验证码通知模块，当自动检测验证码不成功n次(或登录验证码)，会发邮件通知， 人工处理
class captcha_mail(object):
    def __init__(self, addr=None):
        self.from_addr = 'sanyue9394@aliyun.com'
        self.from_passwd = 'sanyue214008'

        #接收邮件的地址， 是个list, 可以填多个地址
        self.to_addr = ['597688801@qq.com']
        if addr:
            self.to_addr.append(addr)

        self.smtp=smtplib.SMTP_SSL()  
        self.smtp.connect('smtp.aliyun.com','465')  
        self.smtp.login(self.from_addr, self.from_passwd)  

    '''
    def __del__(self):
        self.smtp.quit()  
    '''

    def send_mail(self, post_url, captcha_url):
        content = """
        -----------------begin---------------------------
        [self topic]douban work, post_url: %s

        captcha url: %s

        captcha code input: http://47.98.177.0:9903/

        captcha time: %s
        ------------------end----------------------------
        """%(post_url, captcha_url, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()) )

        mail_msg=email.mime.multipart.MIMEMultipart()  
        mail_msg['From']=self.from_addr
        mail_msg['To']=email.utils.COMMASPACE.join(self.to_addr)
        mail_msg['Subject']='captcha new notify'  
        mail_msg['Date'] = email.utils.formatdate(localtime=True)
        text=email.mime.text.MIMEText(content, 'plain', 'utf-8')  
        mail_msg.attach(text)  

        self.smtp.sendmail(self.from_addr, self.to_addr, mail_msg.as_string())  
##send_mail

redis_port=52021
COOKIES_FILE = 'data/cookies.txt'
emoji_re = re.compile(u'('
        u'\ud83c[\udf00-\udfff]|'
        u'\ud83d[\udc00-\ude4f\ude80-\udeff]|'
        u'[\u2600-\u26FF\u2700-\u27BF])+', 
        re.UNICODE)

#self answer mail
self_mail = []
#self topics不回复
my_topics = [106547648,111516608, 112933822, 112932149, 112933816, 112933934, 113515127, 113515502]
#ignore topics
ignore_topics = [106547305, 106547516, 106551311, 113673437, 103217103, 63920532, 154616682, 188712473]

#不回复的豆瓣id
ignore_topic_douban_id = [102393339, 167730677, 168373780]

alive=False
class DoubanRobot:
    '''
    A simple robot for douban.com
    '''
    def __init__(self, account_id, password, douban_id, hotReload=False):
        self.ck = None

        #turing
        self.turi = turibot.chat_turi()
        #redis
        self.redis = redis.StrictRedis(host='localhost', port=redis_port, password='sany')    

        #itchat thread
        self.capt_queue = queue.Queue(1)
        self.sofa_queue = queue.Queue()

        self.captcha = captcha.Captcha()
        #wait input 间隔
        self.captcha_last = time.time()
        #发送邮件间隔
        self.mail_interval = 0
        #自动识别失败次数
        self.mail_fail = 0

        self.sofa_dic = {}
        self.doumail_dic = {}
        self.notify_dic = {}
        self.temp_ignore = {}

        #douban robot
        self.douban_id = str(douban_id)
        self.account_id = account_id
        self.password = password
        self.data = {
                "form_email": self.account_id,
                "form_password": self.password,
                "source": "index_nav",
                "remember": "on",
                "user_login": "登录"
                }
        self.session = requests.Session()
        self.login_url = 'https://www.douban.com/accounts/login'

        self.session.headers = {
                "Connection": "keep-alive",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/59.0.3071.115 Safari/537.36",
                "Origin": "https://www.douban.com",
                }
        # self.session.headers = self.headers
        if not hotReload:
            self.login()
        elif self.load_cookies():
            self.get_ck(None)

    def __del__(self):
        # redis captcha_id 重置
        self.redis.delete('captcha')

    def get_chat(self, msg, uid):
        if '表妹' in msg or '夏文' in msg:
            if msg == '表妹' or msg == '夏文':
                #无意义的喊话， 换成向机器人打招呼
                content = [u'你好', u'你是谁', u'在吗']
                msg = random.choice(content)
            else:
                #替换名称， 让图灵机器人识别(机器人不知'表妹'是在叫它)
                msg = msg.replace('表妹', '你')
                msg = msg.replace('夏文', '你')
        chat_msg = self.turi.get_chat(msg, uid)
        return chat_msg

    def load_cookies(self):
        '''
        load cookies from file.
        '''
        cdir, cbase = os.path.split(COOKIES_FILE)
        if not os.path.isdir(cdir):
            os.makedirs(cdir)
        try:
            with open(COOKIES_FILE, 'rb') as f:
                self.session.cookies = requests.utils.cookiejar_from_dict(pickle.load(f))
            return True
        except Exception as e:
            logging.error('faild to load cookies from file, err:{0}'.format(e))
            return False

    def save_cookies(self, r):
        '''
        save cookies to file.
        '''
        cdir, cbase = os.path.split(COOKIES_FILE)
        if not os.path.isdir(cdir):
            os.makedirs(cdir)
        if r.cookies:
            self.session.cookies.update(r.cookies)
        with open(COOKIES_FILE, 'wb+') as f:
            pickle.dump(requests.utils.dict_from_cookiejar(self.session.cookies), f)
        logging.info('save cookies to file.')

        self.get_ck(r)

    def get_ck(self, r):
        '''
        open douban.com and then get the ck from html.
        '''
        if not r:
            r = self.session.get('https://www.douban.com/accounts/',cookies=self.session.cookies.get_dict())

        cookies = self.session.cookies.get_dict()
        headers = dict(r.headers)
        #save_html('cookies.html',r.text)
        if 'ck' in cookies:
            self.ck = cookies['ck'].strip('"')
            logging.info("ck:%s" %self.ck)
        elif 'Set-Cookie' in headers:
            logging.info('cookies is end of date, login again')
            self.login()
        else:
            logging.error('cannot get the ck.  %s', traceback.format_exc())
            raise Exception('cannot get the ck. ')

    #独立开个线程，从redis 读入数据。 redis 数据在9903 写入， 人工识别验证码
    def input_captcha(self):
        global alive
        if alive:
            return
        alive = True
        try:
            redis_sub = self.redis.pubsub()
            redis_sub.subscribe(['vcode'])
            for item in redis_sub.listen():
                if item['type'] == 'message':
                    vcode = item['data']
                    vcode = vcode.decode('utf-8')
                    self.capt_queue.put(vcode)
                    logging.info('input vcode:%s', vcode)

                    if not vcode in correct.WORDS:
                        correct.WORDS.update(re.findall(r'\w+', vcode))
                        open('static/big.txt', 'a').write('\n%s'%vcode)
                    break
            redis_sub.unsubscribe(['vcode'])
        except:
            logging.error('===input_captcha fail, %s', traceback.format_exc())
        alive = False

    def save_captcha(self, captcha_url):
        #保存captcha
        capt_dir = 'data/captcha/'
        if not os.path.isdir(capt_dir):
            os.makedirs(capt_dir)
        capt_id = self.redis.incrby('capt_id')
        capt_path = os.path.join(capt_dir, 'captcha_%s.png'%capt_id)

        capt_data = urllib.request.urlopen(captcha_url, data=None, timeout=3).read()
        open(capt_path, 'wb').write(capt_data)

    def identify_code_check(self, r, post_url, post_data):
        # 验证码,需要处理
        captcha = re.search('<input type="hidden" name="captcha-id" value="(.+?)"/>', r.text)
        if not captcha:
            captcha = re.search(r"REPLY_FORM_DATA.captcha = {\n\s*id: '(.*?)',", r.text)

        if not captcha:
            return r

        #identify code id
        captcha_id = captcha[1]
        imgurl = "https://www.douban.com/misc/captcha?id={0}&size=s".format(captcha_id)
        logging.info('post_url:%s, post_data:%s, captcha url: %s', post_url, str(post_data), imgurl)
        self.redis.set('captcha', captcha_id)
        
        self.mail_fail += 1
        #reidentify 防止同一个验证码，一直处理不了的情况(captcha_juhe返回None时会重新进identify_code_check, 用时间来判断是不是同一个的)
        reidentify = self.captcha_last and time.time() - self.captcha_last < 1
        #识别验证码失败， 或者触发了豆瓣登陆校验逻辑
        #if r'/login' in post_url or reidentify:
        if self.mail_fail >= 3 or reidentify:
            interval = int(time.time() - self.mail_interval)
            logging.info('captcha mail_interval:%s',  interval)

            # 上一次是30分钟前或是登陆验证的，发邮件通知处理验证码
            if interval > 3*60*60 and self.mail_fail > 3 or r'/login' in post_url:
                logging.info('captcha login mail, notify qq！')
                capt = captcha_mail()
                capt.send_mail(post_url, imgurl)

                self.mail_interval = time.time()

                self.mail_fail = 0

            tt = threading.Thread(target=self.input_captcha)
            tt.start()

            vcode, retry_time = None, 0
            while True:
                try:
                    # 从queue 拿到验证码
                    logging.info('wait for code input:')
                    vcode=self.capt_queue.get(timeout=32*60)
                    logging.info('capt_queue get vcode:%s', vcode)
                    break
                except Exception as e:
                    logging.info('vcode timeout')
                    session = requests.Session()
                    r1 = session.get(imgurl)
                    invalid = re.search(r'<title>页面不存在</title>', r1.text, re.DOTALL)
                    if invalid:
                        #过期
                        logging.info('vcode html expire!!')

                        if r'/login' in post_url:
                            r = self.session.get(post_url, cookies=self.session.cookies.get_dict())
                            captcha = re.search('<input type="hidden" name="captcha-id" value="(.+?)"/>', r.text)
                            if not captcha:
                                logging.info("login captcha check expire.")
                                break
                            else:
                                captcha_id = captcha[1]
                                self.redis.set('captcha', captcha_id)
                                imgurl = "https://www.douban.com/misc/captcha?id={0}&size=s".format(captcha_id)
                                logging.info(r'/login post_url:%s, new captcha url: %s', post_url, imgurl)

                        else:
                            break
                retry_time = retry_time + 1
                if retry_time >= 3:
                    raise Exception('identify  wait break:%s'%retry_time)
        else:
            vcode = self.captcha.captcha_juhe(imgurl)
            logging.info('captcha_juhe get captcha:%s', vcode)

            self.captcha_last = time.time()
            if not vcode:
                #save captcha
                self.save_captcha(imgurl)
                #没有，重新进入mail captcha流程
                return self.identify_code_check(r, post_url, post_data)

        # 登录的自动校验，vcode长度太长的直接放弃
        if 'login' in r.url and (len(vcode) > 8 or len(vcode) <= 4):
            vcode = None

        if 'misc/sorry' in r.url and vcode:
            post_data2 = {}
            post_data2["form_email"] = self.account_id
            post_data2["form_password"] = self.password
            post_data2['ck'] = self.ck
            post_data2["captcha-solution"] = vcode
            post_data2["captcha-id"] = captcha_id
            post_data2['original-url'] = "https://www.douban.com/"
            r = self.session.post(r.url, data=post_data2, cookies=self.session.cookies.get_dict())
        elif vcode:
            if 'login' in r.url or 'account' in r.url:
                post_data["source"] = "index_nav"
                post_data["remember"] = 'on'
                post_data["user_login"] = '登录'
                post_data["form_email"] = self.account_id
                post_data["form_password"] = self.password
            post_data["captcha-solution"] = vcode
            post_data["captcha-id"] = captcha_id
            if 'accounts.douban.com' in r.url:
                post_url = r.url
            r = self.session.post(post_url, data=post_data, cookies=self.session.cookies.get_dict())

        if '验证码错误' in r.text:
            self.save_captcha(imgurl)
        else:
            #成功了
            self.mail_fail = 0

        save_html('identify.html',r.text)

        logging.info('captcha solution:%s, id:%s, url:%s', vcode, captcha_id, r.url)
        #重新检查一次， 若发现还是不行，就，递归
        r = self.identify_code_check(r, post_url, post_data)

        return r

    def login(self):
        '''
        login douban.com and save the cookies to file.
        '''
        self.session.cookies.clear()

        self.session.headers["Referer"] = "https://www.douban.com/"
        r = self.session.post(self.login_url, data=self.data, cookies=self.session.cookies.get_dict())  #核心语句数据从其中传入

        # 验证码
        try:
            r=self.identify_code_check(r, self.login_url, self.data)
        except Exception as e:
            logging.error('login identify err:%s, %s, try again!'%(e, traceback.format_exc()))
            return 
        save_html('login.html', r.text)
        '''
        if r'Your IP is restricted.' in r.text:
            logging.error('login is ban by ip check!! sleep 3 hours..')
            time.sleep(3*60*60)
            return
        '''

        #result
        if r.url == 'https://www.douban.com/':
            self.save_cookies(r)
            logging.info('login successfully!')
        else:
            logging.error('Faild to login, check username and password and captcha code. save error.html, url:%s'%(r.url))
            save_html('login_error.html', r.text)

            self.ck = None

            if 'safety/locked’ in r.url':
                logging.info('safety locked, sleep 4 hours')
                time.sleep(3*60*60)

    def get_my_topics(self):
        homepage_url = self.douban_id.join(['https://www.douban.com/group/people/','/publish'])
        r = self.session.get(homepage_url).text
        topics_list = re.findall(r'<a href="https://www.douban.com/group/topic/([0-9]+)/', r)
        return topics_list

    # 发新帖子
    def new_topic(self, group_id, title, content='Post by python'):
        '''
        use the ck pulish a new topic on the douban group.
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        group_url = "https://www.douban.com/group/" + group_id
        post_url = group_url + "/new_topic"
        post_data = {
                'ck':self.ck,
                'rev_title': title ,
                'rev_text': content,
                'rev_submit':'好了，发言',
                }
        r = self.session.post(post_url, post_data, cookies=self.session.cookies.get_dict())
        # save_html('3.html', r.text)

        # 验证码
        try:
            r=self.identify_code_check(r, post_url, post_data)
        except Exception as e:
            logging.error('new_topic identify err:%s!'%(e))
            return False

        if r.url == post_url:
            logging.info('Okay, new_topic: "%s" post successfully !'%title)
            return True
        return False

    # 发豆瓣的说说
    def talk_status(self, content='Hello.it\'s a test message using python.'):
        '''
        talk a status.
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        post_data = {
                'ck' : self.ck,
                'comment' : content,
                }

        self.session.headers["Referer"] = "https://www.douban.com/"
        r = self.session.post("https://www.douban.com/", post_data, cookies=self.session.cookies.get_dict())
        # save_html('3.html', r.text)
        if r.status_code == 200:
            logging.info('Okay, talk_status: "%s" post successfully !'%content)
            return True

    # 广播邮件
    def broadcast_mail(self, m_text, page_num=0):
        '''
        doumail topics
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        post_url = "https://www.douban.com/doumail/?start=%s"%(page_num*20)

        r = self.session.get(post_url, cookies=self.session.cookies.get_dict())
        #save_html('doumail.html', r.text)

        html = etree.HTML(r.text)
        from_uid = html.xpath("//div[@class='doumail-list']//div[@class='select']/input[@type='checkbox']/@value")
        from_name = html.xpath("//div[@class='doumail-list']//div[@class='title']/div[@class='sender']/span[@class='from']/text()")
        for uid, name in zip(from_uid, from_name):
            if name == '[已注销]':
                continue

            self.send_mail(uid, m_text)

    # 处理未读邮件
    def answer_unread_mail(self, unread=True):
        '''
        doumail topics
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        #1. unread mail
        post_url = "https://www.douban.com/doumail/?start=0"
        r = self.session.get(post_url, cookies=self.session.cookies.get_dict())
        if r'登录豆瓣' in r.text:
            raise Exception('login check fail, need login again!')

        mail_nums = 0
        save_html('unread_mail.html', r.text)
        html = etree.HTML(r.text)
        from_uid = html.xpath("//div[@class='doumail-list']/ul/li[@class='state-unread']/div[@class='select']/input[@type='checkbox']/@value")
        from_name = html.xpath("//div[@class='doumail-list']/ul/li[@class='state-unread']/div[@class='title']/div[@class='sender']/span[@class='from']/text()")
        for uid, name in zip(from_uid, from_name):
            if uid == 'system' or name == '[已注销]':
                continue

            #send mail back to uid
            b_ans = self.answer_mail(uid)
            if b_ans:
                mail_nums = mail_nums + 1

            if b_ans and mail_nums % 4 == 0:
                logging.info("unread mail times:%s, sleep 60's", mail_nums)
                time.sleep(60)
            else:
                time.sleep(1)

        #2. redis unread
        uid = self.redis.lpop('unread_mail')
        while uid:
            uid = uid.decode('utf-8')

            if uid == 'system':
                continue

            #send mail back to uid
            b_ans = self.answer_mail(uid)
            if b_ans:
                mail_nums = mail_nums + 1

            if b_ans and mail_nums % 4 == 0:
                logging.info("rds unread mail times:%s, sleep 60's", mail_nums)
                time.sleep(60)
                if mail_nums >= 8:
                    #不要太多次
                    return mail_nums
            else:
                time.sleep(1)
            uid = self.redis.lpop('unread_mail')

        return mail_nums

    # 回复邮件
    def answer_mail(self, uid):
        msg_id = 0
        if uid in self.doumail_dic:
            msg_id = self.doumail_dic[uid]
        else:
            msg_id = self.redis.get('mail:%s'%(uid)) or 0
            self.doumail_dic[uid] = int(msg_id)
        msg_id = int(msg_id)

        #first mail
        if msg_id == 0:
            chat_msg = u'夏文表妹是机器人，如果她在你发的帖下打扰到你，请允许我在这里向你道歉。回复"夏文二狗"可以获得我联系方式，想要让表妹帮顶贴，想要磁力链接网址，喜欢骑行都可以找我。\n\r代码暂时不公开、机器人不卖、想要做爬虫的同学可以去猪八戒网看看。\n\r\n\r  假如你觉得表妹挺有意思的话，不妨多和她聊聊。\n\r  豆瓣的接口限制了访问频率，邮件回复可能没办法太快，请多多包涵。\n\r  假如表妹没有回复你邮件，可能有豆瓣的验证码表妹自己无法解决， 有时间请帮表妹处理一下: http://magnic.top:9903/'
            send_res = self.send_mail(uid, chat_msg)

        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        post_url = "https://www.douban.com/doumail/{0}/".format(uid)
        self.session.headers["Referer"] = post_url
        r = self.session.get(post_url, cookies=self.session.cookies.get_dict())

        mails = re.findall(r'<div class="chat".*?data="(.*?)">.*?<div class="content">.*?<a href="https://www.douban.com/people/(.*?)/">.*?<p>(.*?)</p>', r.text, re.DOTALL)

        max_id, mail_num = msg_id, 0
        for mail in mails:
            mail_id, send_uid, msg = int(mail[0]), mail[1], mail[2]

            #一次不回复太多消息
            if mail_id <= msg_id:
                logging.info("continue mail_id:%s, msg_id:%s, uid:%s, msg:%s", mail_id, msg_id, send_uid, msg)
                continue

            if send_uid == self.douban_id:
                #self mail
                max_id = max(max_id, mail_id)

                #console
                if 'cmd:stop' == msg:
                    logging.info("stop reply, uid:%s, msg:%s",uid,msg)
                    self.temp_ignore[int(uid)] = time.time()
                    #add self_mail
                    self_mail.append(int(uid))

                    self.send_mail(uid, 'got it, stop reply 60min!')
                elif 'cmd:start' == msg:
                    logging.info("start reply, uid:%s, msg:%s",uid,msg)
                    if int(uid) in self.temp_ignore:
                        del self.temp_ignore[int(uid)]
                    self.send_mail(uid, 'got it, start reply!')

            elif mail_id > msg_id:
                if int(uid) in self.temp_ignore:
                    last_time = self.temp_ignore[int(uid)] or 0
                    #3 min
                    if time.time() - last_time > 3600:
                        del self.temp_ignore[int(uid)]
                    else:
                        max_id = max(max_id, mail_id)
                        continue 
                if mail_num > 3:
                    max_id = max(max_id, mail_id)
                    continue 

                #普通聊天消息
                if '网站' in msg or '磁力链接' in msg or '地址' in msg:
                    chat_msg = '番茄小说: http://tomatow.top/novel. \n\r磁力搜索网站链接: http://tomatow.top/magnetic , 请用电脑打开(如chorme浏览器),下载需要安装迅雷、torrent(磁力链接下载);\n\r可以的话，不妨关注一下。:)\n\r假如电影的话，推荐“至暗时刻”，记录片的“蓝色星球”也不错。小电影的话，关键字可以是“学妹、合集、小美女"等等，看你个人偏好吧。 如果有什么建议，不妨留言回复一下 :)\n\r'
                elif "蒸" in msg or "征" in msg:
                    content = ['好看的皮囊三千一晚，有趣的灵魂要房要车。', '选我！选我！', '"别找了找不到的，你还在想些什么"', '除了有趣，还有什么别的具体要求吗']
                    chat_msg = random.choice(content)
                elif '夏文二狗' in msg:
                    chat_msg = '表妹不够智能，如果回复让你误会了， 请让我先道歉。\n\r可以加我微信,"iamxiaomaomao", 我一定给你个满意答复。'
                else:
                    chat_msg = self.get_chat(msg, uid)

                if int(uid) in self_mail:
                    max_id = max(max_id, mail_id)
                    continue

                send_res = self.send_mail(uid, chat_msg)

                #send mail fail
                if not send_res:
                    logging.error('send_mail fail, uid:%s, msg:%s, lpush unread_mail', uid, msg)
                    self.redis.lpush('unread_mail', uid)
                else:
                    logging.info("[mail]:%s, mail:%s, answer:%s", uid, msg, chat_msg)
                    max_id = max(max_id, mail_id)
                    mail_num = mail_num + 1

        if max_id > msg_id:
            self.doumail_dic[uid] = int(max_id)
            self.redis.set('mail:%s'%(uid), int(max_id))
        return True

    # 主动向某个uid发邮件
    def send_mail(self, uid, content = '测试豆油，keep moving!'):
        '''
        send a doumail to other.
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        if int(uid) == 1614631:
            logging.error('--send_mail 1614631 :%s', traceback.format_stack()[0])
            return True

        post_data = {
                "ck" : self.ck,
                "m_text" : '表妹：' + content,
                "m_image" : '',
                "to" : uid,
                }
        self.session.headers["Referer"] = "https://www.douban.com/doumail/%s/"%(uid)
        post_url = "https://www.douban.com/j/doumail/send"

        try:
            r = self.session.post(post_url, post_data, cookies=self.session.cookies.get_dict(), timeout=10)
            # 验证码
            r=self.identify_code_check(r, post_url, post_data)

            res = json.loads(r.text)
            if "error" in res:
                logging.error('send_mail fail, url:j/doumail/send, got error!!, post_data:%s, r.error:%s', str(post_data), res['error'])
                save_html('j_doumail_send.html', r.text)

                #换一个方法， send one more time
                post_data['m_submit'] = '好了，寄出去'
                post_url = "https://www.douban.com/doumail/write?to=%s"%(uid)
                r = self.session.post(post_url, post_data, cookies=self.session.cookies.get_dict())

                # 验证码
                r=self.identify_code_check(r, post_url, post_data)

                save_html('retry_mail.html', r.text)

                logging.error('send_mail retry once, url:doumail/write, r.url:%s, save retry_mail.html', r.url)
                return True 
            if "r" in res and res["r"] != 0:
                logging.error('send_mail fail, url:j/doumail/send, text:%s', r.text)

                self.login()
                return False

            logging.info('Okay, send_mail: To %s doumail "%s", %s', uid, r.url, r.text)
        except Exception as e:
            logging.error('send_mail identify err:%s! not try again', traceback.format_exc() )
            # save_html('mail_error2.html', r.text)
            return False

        return True


    # 顶贴
    #topics_list = app.get_my_topics()
    #app.topics_up(topics_list)
    def topics_up(self,
            topics_list,
            content=['顶',
                '顶帖',
                '自己顶',
                'waiting',]
            ):
        '''
        Randomly select a content and reply a topic.
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')


        # For example --> topics_list = ['22836371','98569169']
        #topics_list = ['22836371','98569169']
        for item in topics_list:
            post_data = {
                    "ck" : self.ck,
                    "rv_comment" : random.choice(content),
                    "start" : "0",
                    "submit_btn" : "加上去"
                    }
            post_url = "https://www.douban.com/group/topic/%s/add_comment#last?"%(item)
            r = self.session.post(post_url, post_data, cookies=self.session.cookies.get_dict())
            
            try:
                r=self.identify_code_check(r, post_url, post_data)
            except Exception as e:
                logging.error('topics_up %s identify err:%s!'%(item, e))
                continue

            if r.status_code == 200:
                logging.info('Okay, already up %s topic', item)

            html = etree.HTML(r.text)
            logo = html.xpath("//div[@class='wrapper']/div[@id='header']/a[@class='logo']/text()")
            if logo and logo[0] == '登录豆瓣':
                #需要重登
                raise Exception('relogin require')

            if '检测到有异常请求从你的 IP 发出' in r.text:
                raise Exception('IP check fail, try relogin.')
            save_html('%s.html'%item, r.text)
            logging.info("topic up:%s success:%s, sleep 3's", item, post_data['rv_comment'])
            time.sleep(5*60)  # Wait a minute to up next topic, You can modify it to delay longer time
        return True

    # 删帖子上自己的发言
    def delete_comment(self, topic_id):
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        for page in range(0, 1000, 100):
            post_url = "https://www.douban.com/group/topic/%s/?start=%s"%(topic_id, page)

            r = self.session.get(post_url, cookies=self.session.cookies.get_dict())
            html = etree.HTML(r.text)
            cids = html.xpath("//li[@class='clearfix comment-item']/@data-cid")
            uids = html.xpath("//li[@class='clearfix comment-item']/div[@class='reply-doc content']/div[@class='operation_div']/@id")

            if len(cids) == 0 or len(uids) == 0:
                #delete success
                logging.info('topic %s delete_comment success!', topic_id)
                return True

            remove_url = "https://www.douban.com/j/group/topic/%s/remove_comment"%(topic_id)
            for cid, uid in zip(cids, uids):
                if uid != self.douban_id:
                    continue
                # Leave last comment and delete all of the past comments
                post_data = {
                        "ck"  : self.ck,
                        "cid" : cid
                        }
                r = self.session.post(remove_url, post_data, cookies=self.session.cookies.get_dict())

                if r.status_code == 200:
                    logging.info('Okay, already delete %s topic:%s', topic_id, cid )  # All of them return 200... Even if it is not your comment
                time.sleep(1)  # Wait ten seconds to delete next one

        return True

    # 开新线程，去查看有没沙发需要顶
    def sofa_monitor(self, session, group_id):

        group_url = "https://www.douban.com/group/" + group_id +"/#topics"

        #减少账号连接session请求数
        #r = self.session.get(group_url, cookies=self.session.cookies.get_dict())
        r =session.get(group_url, cookies=session.cookies.get_dict())
        topics = re.findall(r'<a href="https://www.douban.com/group/topic/(\d+?)/" title="(.*?)" class="">.*?"https://www.douban.com/people/(\d+?)/" class="">(.*?)</a></td>', r.text, re.DOTALL)
        #save_html('sofa_%s.html'%group_id, r.text)

        sofa_time = 0
        for item in topics:
            topic_id, title, uid, nickname = item[0], item[1], item[2], item[3]
            exists = topic_id in self.sofa_dic
            if not exists:
                exists = self.redis.exists('sofa:%s'%topic_id)
            else:
                continue

            #过滤
            if int(uid) in ignore_topic_douban_id:
                self.redis.set('sofa:%s'%topic_id, 1)
                self.sofa_dic[topic_id] = True
                return True

            #redis那次的过滤,exists
            self.sofa_dic[topic_id] = True
            if not exists:
                sofa_item = [topic_id, title, uid, nickname]
                self.sofa_queue.put(sofa_item)

                sofa_time = sofa_time + 1

        if sofa_time>0:
            logging.info('%s sofa_monitor event:%s', group_id, sofa_time)

        return sofa_time

    def sofa_qsize(self):
        return self.sofa_queue.qsize()

    def sofa(self, times=0):
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        if self.sofa_queue.empty():
            return 0

        sofa_time = 0
        while times>0:
            times = times-1
            try:
                sofa_item = self.sofa_queue.get(timeout=1)
            except Exception as e:
                #没有sofa数据了
                break

            topic_id, title, uid, nickname = sofa_item[0], sofa_item[1], sofa_item[2], sofa_item[3]
            post_url = "https://www.douban.com/group/topic/" + topic_id + "/add_comment#last?"

            title = emoji_re.sub(r'', title)
            chat_msg = self.get_chat(title, uid)
            logging.info(u"topic:%s, uid:%s[%s], [%s], up:%s",topic_id, uid, nickname, title, chat_msg)

            post_data = {
                    "ck" : self.ck,
                    "rv_comment" : chat_msg,
                    "start" : "0",
                    "submit_btn" : "加上去"
                    }
            r = self.session.post(post_url, post_data, cookies=self.session.cookies.get_dict())

            if r'登录豆瓣' in r.text or '检测到有异常请求从你的 IP 发出' in r.text:
                logging.info('login check, need login again!')
                self.login()
                return sofa_time

            # 验证码
            try:
                r=self.identify_code_check(r, post_url, post_data)
            except Exception as e:
                logging.error('sofa identify err:%s!'%(e))
                return sofa_time

            if r.status_code == 200:
                self.redis.set('sofa:%s'%topic_id, uid)
                logging.info('[sofa],https://www.douban.com/group/topic/%s:"%s" successfully!'%(topic_id, chat_msg))
                save_html('sofa.html', r.text)
            elif '页面不存在' in r.text or '您已被禁言' in r.text:
                #删帖了
                self.sofa_dic[topic_id] = True
            else:
                self.sofa_dic[topic_id] = False

                save_html('sofa_fail.html', r.text)
                logging.error('sofa fail, topic id:%s, sleep 180s', topic_id)
                time.sleep(1800)

            sofa_time = sofa_time + 1
            #避免sofa_time一直是4
            time.sleep(3)

        return sofa_time

    def answer_unread_notify(self):
        '''
        doumail topics
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        post_url = "https://www.douban.com/notification/"
        self.session.headers["Referer"] = post_url
        r = self.session.get(post_url, cookies=self.session.cookies.get_dict())
        if r'登录豆瓣' in r.text or '检测到有异常请求从你的 IP 发出' in r.text:
            logging.info('login check, need login again!')
            self.login()
            return 0
            #raise Exception('login check fail, need login again!')
        #save_html('notifycation.html', r.text)

        notifys = re.findall(r'<div id="reply_notify_(\d*)" class="item-req ">.*?<a href="https://www.douban.com/group/topic/(\d*)/\?start=(\d*)#(\d*)" target="_blank">(.*?)</a>(.*?)\n', r.text, re.DOTALL)

        notify_nums = 0
        for notify in notifys:
            notify_id, topic_id, start, cid, short, short = notify[0], notify[1], notify[2], notify[3], notify[4], notify[5]

            if int(topic_id) in my_topics or int(topic_id) in ignore_topics:
                continue

            #点赞的评论
            if '赞' in short:
                self.answer_like(notify_id, topic_id, start, cid)
                continue

            b_ans = self.answer_notify(notify_id, topic_id, start, cid)
            if b_ans:
                notify_nums = notify_nums + 1
            if b_ans and notify_nums % 4 == 0:
                logging.info("answer_notify nums:%s, break and sleep", notify_nums)
                break
            elif b_ans:
                #每个notify直接间隔
                time.sleep(1)

        time.sleep(3)

        return notify_nums

    def answer_like(self, notify_id, topic_id, start, cid):
        exists = notify_id in self.notify_dic
        if not exists:
            exists = self.redis.exists('notify:%s'%notify_id)
        else:
            return False
        
        if not exists:
            logging.info('--add like, notify:https://www.douban.com/group/topic/%s/?start=%s#%s, 有了1次赞', topic_id, start, cid)
            like_key = 'notify_like'
            cid_key = r'%s/?start=%s#%s'%(topic_id, start, cid)
            self.redis.zincrby(like_key, cid_key, 1)

            self.redis.set('notify:%s'%notify_id, 1)
            self.notify_dic[notify_id] = True
        else:
            self.notify_dic[notify_id] = True
            return False

        return True


    def answer_notify(self, notify_id, topic_id, start, cid):
        exists = notify_id in self.notify_dic
        if not exists:
            exists = self.redis.exists('notify:%s'%notify_id)
        else:
            return False

        if not exists:
            post_url = "https://www.douban.com/group/topic/{0}/?start={1}#{2}".format(topic_id, start, cid)
            self.session.headers["Referer"] = post_url
            r = self.session.get(post_url, cookies=self.session.cookies.get_dict())

            topics = re.findall(r'data-cid="{0}".*?<div class="reply-quote">.*?<p class="">(.*?)</p>.*?<div class="operation_div" id="(\d*)">'.format(cid), r.text, re.DOTALL)

            if not topics or len(topics)==0 :
                self.redis.set('notify:%s'%notify_id, 1)
                self.notify_dic[notify_id] = True
                logging.error('answer notify:%s fail, cid:%s', notify_id, cid)
                return False

            topic = topics[0]
            content, uid = topic[0], topic[1]

            #self topic
            if uid == self.douban_id or int(uid) in ignore_topic_douban_id:
                self.redis.set('notify:%s'%notify_id, 1)
                self.notify_dic[notify_id] = True
                return False

            #get turi chat msg
            chat_msg = self.get_chat(content, uid)
            post_data = {
                    "ck" : self.ck,
                    "rv_comment" : chat_msg,
                    "ref_cid" : cid,
                    "start" : start,
                    "submit_btn" : "加上去",
                    "start" : 0,
                    }
            post_url2 = "https://www.douban.com/group/topic/" + str(topic_id) + "/add_comment#last"
            self.session.headers["Referer"] = post_url2
            r = self.session.post(post_url2, post_data, cookies=self.session.cookies.get_dict())
            # 验证码
            try:
                r=self.identify_code_check(r, post_url2, post_data)
            except Exception as e:
                logging.error('answer_notify identify err:%s!'%(e))
                raise Exception('notify identify fail, try relogin')

            if r.status_code == 200:
                self.redis.set('notify:%s'%notify_id, 1)
                self.notify_dic[notify_id] = True
                logging.info('Okay, [%s] uid:%s, content:%s, notify:"%s" successfully!'%(post_url, uid, content, chat_msg))
            else:
                save_html('notify_fail.html', r.text)
                logging.error('notify fail, topic id:%s', topic_id)
                if '没有访问权限' not in r.text:
                    raise Exception('notify fail, try relogin')
        else:
            self.notify_dic[notify_id] = True
            return False

        return True

    def discuss_spider(self, start_id=0):
        '''
        discuss spider
        '''
        if not self.ck:
            logging.error('ck is invalid!')
            raise Exception('login fail, ck is invalid')

        post_url = "https://www.douban.com/group/GuangZhoulove/discussion?start=%s"%(start_id)
        self.session.headers["Referer"] = post_url
        r = self.session.get(post_url, cookies=self.session.cookies.get_dict())

        notifys = re.findall(r'<td class="title">.*?<a href="https://www.douban.com/group/topic/(\d*)/" title="(.*?)".*?class="time">(.*?)</td>', r.text, re.DOTALL)
        for notify in notifys:
            topic_id, title, topic_time = notify[0], notify[1], notify[2]
            if self.redis.hget('discuss', topic_id) != None:
                logging.error('repeat topic_id:%s, start_id:%s', topic_id, start_id)
                continue 

            post_url = "https://www.douban.com/group/topic/%s/"%(topic_id)
            self.session.headers["Referer"] = post_url
            r = self.session.post(post_url, post_data, cookies=self.session.cookies.get_dict())

            contents = re.findall(r'<div class="topic-content">.*?<p>(.*?)</p>', r.text, re.DOTALL)
            content = ''
            if len(contents)!=0:
                content = contents[0]

            text = {'topic':topic_id, 'title':title, 'content':content, 'time':topic_time}
            with codecs.open('douban/%s.txt'%(topic_id), 'w+', encoding='utf-8') as f:
                f.write(json.dumps(text))

            self.redis.hset('discuss', topic_id, 1)
            time.sleep(3)

def save_html(name, data):
    save_dir='html/'
    if not os.path.isdir(save_dir):
        os.makedirs(save_dir)
    save_path = save_dir+name
    with codecs.open(save_path, 'w', encoding='utf-8') as f:
        f.write(data)

def save_image(imgurl, captcha):
    imgdata = urllib.request.urlopen(imgurl, data=None, timeout=3).read()
    with open(captcha, 'wb') as image:
        image.write(imgdata)


circle_times = 0
def monitor_work(douban, circle_num):
    global circle_times

    logging.info('monitor work start, circle_num:%s', circle_num)
    session = requests.Session()
    session.headers = {
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.2pre) Gecko/20070215 K-Ninja/2.1.1",
            "Origin": "https://www.douban.com",
            }
    '''
    session.proxies = {
            'http': 'socks5://127.0.0.1:1080',
            'https': 'socks5://127.0.0.1:1080',
            }
    '''
    while circle_times == circle_num:
        try:
            qsize = douban.sofa_qsize()

            sofa_group = ['GuangZhoulove', '596537', '613361', 'liveinguangzhou']
            #sofa_group.append('gz')
            sofa_num = 0
            for group_id in sofa_group:
                size = douban.sofa_monitor(session, group_id)
                sofa_num = sofa_num + size
                time.sleep(3)

            tm = time.localtime()
            if tm.tm_hour >= 3 and tm.tm_hour < 5:
                #凌晨3点到4点， sleep 2.5 hours
                tt = 152*60
            elif tm.tm_hour>=5 and tm.tm_hour <7:
                #凌晨5点到7点， sleep 30 mins
                tt = 30*60
            elif sofa_num < 4 and qsize > 12:
                tt = 6*60
            elif sofa_num > 0 and qsize < 4:
                tt = 60
            else:
                tt = 3*60

            logging.info("monitor_work sofa_num:%s, qsize:%s, sleep %s's", sofa_num, douban.sofa_qsize(), tt)
            time.sleep(tt)
        except Exception as e:
            logging.error("monitor work raise Exception, sleep 15'mins, %s",traceback.format_exc())
            time.sleep(15*60)
            session = requests.Session()
            session.headers = {
                "Connection": "keep-alive",
                "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.2pre) Gecko/20070215 K-Ninja/2.1.1",
                "Origin": "https://www.douban.com",
                }


def work(hotReload=False):
    global circle_times
    account_id =  '13533092312'    # your account no (E-mail or phone number)
    #password   =  'adder911002'    # your account password
    password   =  'ADDER1002mdc'    # your account password
    douban_id  =  '161638302'    # your id number

    douban = DoubanRobot(account_id, password, douban_id, hotReload=hotReload)
    tt = threading.Thread(target=monitor_work, args=(douban, circle_times))
    tt.start()

    #等待 monitor线程
    time.sleep(3)

    while True:
        try:
            #循环处理多少次
            #times_unread_mail, times_unread_notify, times_sofa = 5, 3, 3
            # 2018/10/25 发现回复消息可能会导致封禁(无法避免，每次都是凌晨4.30封禁，应该是豆瓣有跑检查发帖数量来判断的逻辑)， 只开邮件和沙发功能
            times_unread_mail, times_unread_notify, times_sofa = 5, 3, 3
            while times_unread_mail > 0 or times_unread_notify > 0 or times_sofa > 0:
                if times_unread_mail > 0:
                    len_mail = douban.answer_unread_mail()
                    logging.info('get_mail[%s]:%s', times_unread_mail, len_mail)
                    if len_mail == 0:
                        times_unread_mail = times_unread_mail - 3
                    else:
                        times_unread_mail = times_unread_mail - 1

                #有豆油时，优先豆油(最后一次还是处理一下notify， sofa那些)
                if len_mail > 0 and times_unread_mail > 0:
                    times_unread_notify = times_unread_notify - 1
                    times_sofa = times_sofa - 1

                    logging.info("work, give priority to mail answer, sleep 30's, unread_time:%s", times_unread_mail)
                    time.sleep(len_mail*15)

                    continue
  
                if times_unread_notify > 0:
                    len_notify = 0
                    #len_notify = douban.answer_unread_notify()
                    logging.info('get_notify[%s]:%s', times_unread_notify, len_notify)
                    if len_notify == 0:
                        times_unread_notify = 0
                    else:
                        times_unread_notify = times_unread_notify - 1

                if len_mail > 0 or len_notify > 0 :
                    logging.info("mail:%s, notify:%s, sleep 60's", len_mail, len_notify)
                    time.sleep(len_mail*15+len_notify*15)

                if times_sofa > 0:
                    len_sofa = douban.sofa(4)
                    if len_sofa == 0:
                        times_sofa = 0
                    else:
                        times_sofa = times_sofa - 1
                    if len_sofa > 0:
                        logging.info("get_sofa[%s]:times:%s, sleep 60's", times_sofa, len_sofa)
                        time.sleep(len_sofa*15)

                logging.info('---- while')

            logging.info("work finished, sleep 3*60's")

            tm = time.localtime()
            if tm.tm_hour >= 3 and tm.tm_hour < 5:
                #凌晨3点到4点， sleep 2.5 hours
                time.sleep(152*60)
            elif tm.tm_hour>=5 and tm.tm_hour <7:
                #凌晨5点到7点， sleep 30 mins
                time.sleep(30*60)
            else:
                #3 mins
                time.sleep(3*60)

            logging.info('==== work')
        except Exception as e:
            logging.error("daily work raise exception:%s, sleep 15*60's",traceback.format_exc())
            douban = None

            circle_times = circle_times + 1
            tt.join()

            if 'Remote end closed connection without response' in traceback.format_exc() or 'Connection reset by peer' in traceback.format_exc():
                time.sleep(10*60)
                logging.info("Remote and closed connection, try reconnect after 10*60's")
                douban = DoubanRobot(account_id, password, douban_id, hotReload=True)
            elif 'try relogin1' in traceback.format_exc():
                time.sleep(15*60)
                douban = DoubanRobot(account_id, password, douban_id, hotReload=False)
            else:
                time.sleep(15*60)
                douban = DoubanRobot(account_id, password, douban_id, hotReload=True)

            tt = threading.Thread(target=monitor_work, args=(douban, circle_times))
            tt.start()


if __name__ == '__main__':
    log_dir = 'log/'
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    logging.basicConfig(level=logging.INFO,
            format='[%(asctime)s %(name)-12s %(levelname)-s] %(message)s',
            datefmt='%m-%d %H:%M:%S',
            #filename=time.strftime('log/doubanrobot.log'),
            filemode='a')

    htimed = logging.handlers.TimedRotatingFileHandler("log/doubanrobot.log", 'D', 1, 0)
    htimed.suffix = "%Y%m%d-%H%M"
    htimed.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s %(name)-12s %(levelname)-s] %(message)s', datefmt='%m-%d %H:%M:%S')
    htimed.setFormatter(formatter)

    logging.getLogger('').addHandler(htimed)

    ##bind Port
    import socket

    Port = 8901
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # 绑定端口，端口占用表示程序正在运行
        sock.bind(('127.0.0.1', Port))
        sock.listen(5)
    except:
        logging.error('socket bind(%s) fail, analyze work already start!!', Port)
        os._exit(0)

    import sys
    if len(sys.argv) > 1 and sys.argv[1]=='run':
        work()
    else:
        work(hotReload=True)

