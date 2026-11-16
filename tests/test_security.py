import base64
import io
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from flask.testing import FlaskClient
from PIL import Image
import app as A
from test_app import client, register, H


def own_farm(c):
    c.post('/farms/add', data=dict(farm_name='PRIVATE-OWNER-MARKER',crop_type='Rice',location='Chattogram',area=1,planting_date='2026-01-01'), headers=H)
    conn=A.get_db();r=conn.execute('SELECT id FROM farms ORDER BY id DESC').fetchone();conn.close();return r[0]

@pytest.mark.parametrize('path,table,data',[
 ('/growth/add','crop_growth',dict(planting_date='2026-01-01')),
 ('/irrigation/add','irrigation_log',dict(date='2026-01-01',water_liters=10,duration_min=2)),
 ('/expenses/add','expense_log',dict(date='2026-01-01',amount=100))])
def test_cross_owner_creation_blocked(client,path,table,data):
    register(client,'owner@example.test');fid=own_farm(client)
    other=A.app.test_client();register(other,'other@example.test')
    assert other.post(path,data={**data,'farm_id':fid},headers=H).status_code==404
    conn=A.get_db();assert conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0;conn.close()
    assert client.post(path,data={**data,'farm_id':fid},headers=H).status_code==302

@pytest.mark.parametrize('table,page,columns,values',[
 ('crop_growth','/growth','planting_date',('2026-01-01',)),
 ('irrigation_log','/irrigation','date',('2026-01-01',)),
 ('expense_log','/expenses','date,type,amount',('2026-01-01','expense',10))])
def test_legacy_cross_owner_join_hidden(client,monkeypatch,table,page,columns,values):
    monkeypatch.setattr('requests.get',lambda *a,**kw:SimpleNamespace(json=lambda:{}))
    register(client,'owner@example.test');fid=own_farm(client)
    other=A.app.test_client();register(other,'other@example.test')
    conn=A.get_db();conn.execute('INSERT INTO '+table+' (farm_id,user_id,'+columns+') VALUES ('+','.join('?' for _ in range(len(values)+2))+')',(fid,2,*values));conn.commit();conn.close()
    r=other.get(page);assert r.status_code==200;assert b'PRIVATE-OWNER-MARKER' not in r.data


def test_unused_login_cookie_revoked(client):
    register(client)
    stale=A.app.test_client();stale.post('/login',data=dict(email='a@b.co',password='password1'),headers=H)
    client.post('/profile',data=dict(action='change_password',current_password='password1',new_password='changedpassword2',confirm_password='changedpassword2'),headers=H)
    assert stale.get('/account/export').status_code==302


def test_legacy_session_rejected_and_database_failure_closed(client,monkeypatch):
    register(client)
    with client.session_transaction() as s:s.pop('sv')
    assert client.get('/api/farms').status_code==401
    register(client,'other@example.test')
    def fail():raise RuntimeError('database unavailable')
    monkeypatch.setattr(A,'get_db',fail)
    assert client.get('/api/farms').status_code==503


def test_csrf_requires_token_even_with_no_origin(client):
    raw=FlaskClient(A.app)
    assert raw.post('/login',data=dict(email='a@b.co',password='password1')).status_code==403
    assert raw.post('/login',data={},headers=H).status_code==403
    assert b'name="csrf_token"' in raw.get('/login').data
    with raw.session_transaction() as s:token=s['csrf_token']
    assert raw.post('/login',data=dict(email='a@b.co',password='password1'),headers={'X-CSRF-Token':token}).status_code==200
    assert raw.post('/login',data={},headers={'X-CSRF-Token':token,'Origin':'https://evil.test'}).status_code==403


def test_logout_get_has_no_side_effect(client):
    register(client)
    assert client.get('/logout').status_code==200
    assert client.get('/account/export').status_code==200
    assert client.post('/logout',headers=H).status_code==302
    assert client.get('/account/export').status_code==302


def subscription(endpoint='https://fcm.googleapis.com/fcm/send/test'):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
    key=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(Encoding.X962,PublicFormat.UncompressedPoint)
    enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
    return {'endpoint':endpoint,'expirationTime':None,'keys':{'p256dh':enc(key),'auth':enc(b'x'*16)}}

@pytest.mark.parametrize('endpoint',['https://127.0.0.1/a','https://169.254.169.254/a','https://localhost/a','https://fcm.googleapis.com.evil.test/a','https://fcm.googleapis.com@evil.test/a','http://fcm.googleapis.com/a','https://fcm.googleapis.com:444/a','https://fcm.googleapis.com/a#bad'])
def test_push_ssrf_rejected(client,monkeypatch,endpoint):
    monkeypatch.setattr(A,'PUSH_ENABLED',True);register(client)
    assert client.post('/api/push/subscribe',json=subscription(endpoint),headers=H).status_code==400


def test_push_ownership_and_send_revalidation(client,monkeypatch):
    monkeypatch.setattr(A,'PUSH_ENABLED',True);register(client)
    sub=subscription();assert client.post('/api/push/subscribe',json=sub,headers=H).status_code==200
    other=A.app.test_client();register(other,'other@example.test')
    assert other.post('/api/push/subscribe',json=sub,headers=H).status_code==409
    import pywebpush
    calls=[];monkeypatch.setattr(pywebpush,'webpush',lambda **kw:calls.append(kw))
    assert A.send_push({'endpoint':'https://localhost/internal','p256dh':'x','auth':'y'}, {})=='gone'
    assert not calls
    assert A.send_push({'endpoint':sub['endpoint'],**sub['keys']},{'body':'test'})=='ok'
    assert calls[0]['timeout']==10
    import requests
    seen=[]
    monkeypatch.setattr(requests.Session,'request',lambda self,*args,**kw:seen.append(kw))
    calls[0]['requests_session'].get(sub['endpoint'],allow_redirects=True)
    assert seen[0]['allow_redirects'] is False


def test_reset_tokens_never_logged(client,monkeypatch,capsys,caplog):
    monkeypatch.setattr(A,'MAIL_ENABLED',False)
    assert not A.send_reset_email('test@example.test','Test','https://example.test/reset-password/PRIVATE-TOKEN-MARKER')
    assert 'PRIVATE-TOKEN-MARKER' not in capsys.readouterr().out+caplog.text


def test_account_and_farm_deletion_remove_owned_records(client):
    register(client);fid=own_farm(client)
    for path,data in [('/growth/add',dict(planting_date='2026-01-01')),('/irrigation/add',dict(date='2026-01-01')),('/expenses/add',dict(date='2026-01-01',amount=10))]:
        assert client.post(path,data={**data,'farm_id':fid},headers=H).status_code==302
    client.post('/farms/delete/'+str(fid),headers=H)
    conn=A.get_db()
    for t in ['crop_growth','irrigation_log','expense_log']:assert conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==0
    conn.execute("INSERT INTO password_resets (user_id,token,expires_at) VALUES (1,'dummy','2099-01-01')")
    conn.execute("INSERT INTO push_log (user_id,task_id,day) VALUES (1,'test','2026-01-01')")
    conn.execute("INSERT INTO push_subs (user_id,endpoint,p256dh,auth) VALUES (1,'dummy','dummy','dummy')")
    conn.execute("INSERT INTO price_history (user_id,crop,price,day) VALUES (1,'Rice',20,'2026-01-01')");conn.commit();conn.close()
    client.post('/profile',data=dict(action='delete_account',delete_password='password1',delete_confirm='DELETE'),headers=H)
    conn=A.get_db()
    for t in ['users','farms','crop_notes','disease_scans','crop_growth','irrigation_log','expense_log','fertilizer_history','password_resets','push_log','push_subs','price_history']:
        assert conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==0,t
    conn.close()

@pytest.mark.parametrize('path,data',[
 ('/farms/add',{'area':'NaN'}),('/farms/edit/1',{'area':'-1'}),('/growth/add',{'expected_days':'bad'}),
 ('/growth/add',{'planting_date':'2026-99-99'}),('/irrigation/add',{'water_liters':'-5'}),
 ('/expenses/add',{'amount':'Infinity'}),('/profile',{'avatar_color':'red;background:url(https://evil.test)'}),
 ('/register',{'email':'invalid'})])
def test_invalid_input_returns_400(client,path,data):
    register(client);assert client.post(path,data=data,headers=H).status_code==400

@pytest.mark.parametrize('body',[[],[1],{'area':{}},{'area':'nan'},{'area':-1}])
def test_bad_json_not_500(client,body):
    register(client);assert client.post('/api/fertilizer',json=body,headers=H).status_code==400


def test_profile_image_decoded_and_metadata_removed(client):
    register(client)
    client.post('/profile',data={'action':'upload_photo','profile_photo':(io.BytesIO(b'not an image'),'a.png','image/png')},headers=H)
    assert client.get('/avatar/1').status_code==404
    data=io.BytesIO();Image.new('RGB',(10,10)).save(data,format='PNG');data.seek(0)
    client.post('/profile',data={'action':'upload_photo','profile_photo':(data,'a.png','image/png')},headers=H)
    r=client.get('/avatar/1');assert r.status_code==200;assert r.mimetype=='image/jpeg'


def test_shared_quota_atomic_and_forwarded_header_ignored(client,monkeypatch):
    with ThreadPoolExecutor(max_workers=6) as ex:results=list(ex.map(lambda _:A.rate_allow('parallel-test',3,60),range(12)))
    assert sum(results)==3
    A._throttle_hits.clear();assert not A.rate_allow('parallel-test',3,60)
    monkeypatch.delenv('TRUST_PROXY_HEADERS',raising=False)
    with A.app.test_request_context('/',headers={'X-Forwarded-For':'spoofed'}):assert A.client_ip()!='spoofed'


def test_reset_single_use_and_change_invalidates_pending_reset(client):
    register(client)
    conn=A.get_db();conn.execute('INSERT INTO password_resets (user_id,token,expires_at) VALUES (?,?,?)',(1,A.hash_token('dummy-token'),(datetime.now()+timedelta(hours=1)).isoformat()));conn.commit();conn.close()
    other=A.app.test_client()
    assert other.post('/reset-password/dummy-token',data=dict(new_password='newpassword2',confirm_password='newpassword2'),headers=H).status_code==302
    assert client.get('/account/export').status_code==302
    assert other.get('/reset-password/dummy-token').status_code==302


def test_private_responses_no_store(client):
    register(client)
    for path in ['/profile','/dashboard','/api/farms','/account/export']:
        r=client.get(path);assert r.status_code==200;assert 'no-store' in r.headers['Cache-Control']

@pytest.mark.parametrize('userinfo',[{'sub':'a','email':'a@b.co','email_verified':False},{'sub':'','email':'a@b.co','email_verified':True}])
def test_google_rejects_unverified_claims(client,monkeypatch,userinfo):
    monkeypatch.setattr(A,'GOOGLE_OAUTH_ENABLED',True)
    monkeypatch.setattr(A,'google',SimpleNamespace(authorize_access_token=lambda:{'userinfo':userinfo}),raising=False)
    assert client.get('/login/google/callback').status_code==302
    with client.session_transaction() as s:assert 'user_id' not in s


def test_google_does_not_auto_link_password_account(client,monkeypatch):
    register(client)
    other=A.app.test_client()
    monkeypatch.setattr(A,'GOOGLE_OAUTH_ENABLED',True)
    monkeypatch.setattr(A,'google',SimpleNamespace(authorize_access_token=lambda:{'userinfo':{'sub':'test-subject','email':'a@b.co','email_verified':True}}),raising=False)
    other.get('/login/google/callback')
    with other.session_transaction() as s:assert 'user_id' not in s


def test_other_user_cannot_read_or_delete_farm(client):
    register(client);fid=own_farm(client)
    other=A.app.test_client();register(other,'other@example.test')
    assert other.get('/api/farm/'+str(fid)).status_code==404
    other.post('/farms/delete/'+str(fid),headers=H)
    assert client.get('/api/farm/'+str(fid)).status_code==200
    assert other.get('/account/export').get_json()['farms']==[]


def test_ai_photo_normalization_strips_metadata():
    import vision
    data=io.BytesIO();im=Image.new('RGB',(20,20));exif=Image.Exif();exif[0x010E]='PRIVATE-LOCATION-MARKER'
    im.save(data,format='JPEG',exif=exif)
    assert b'PRIVATE-LOCATION-MARKER' in data.getvalue()
    clean=vision.normalize_photo(data.getvalue())
    assert b'PRIVATE-LOCATION-MARKER' not in clean
    assert Image.open(io.BytesIO(clean)).size==(20,20)
    with pytest.raises(vision.VisionError):vision.normalize_photo(b'\xff\xd8\xffnot-real')


def test_all_html_pages_and_inline_javascript_parse(client,tmp_path,monkeypatch):
    from html.parser import HTMLParser
    import subprocess, shutil
    if not shutil.which('node'):pytest.skip('Node required for inline JS syntax validation')
    monkeypatch.setattr('requests.get',lambda *a,**kw:SimpleNamespace(json=lambda:{}))
    class Scripts(HTMLParser):
        def __init__(self):super().__init__();self.parts=[];self.inside=False
        def handle_starttag(self,t,a):
            if t=='script':self.inside=True;self.parts.append('')
        def handle_endtag(self,t):
            if t=='script':self.inside=False
        def handle_data(self,d):
            if self.inside:self.parts[-1]+=d
    register(client);own_farm(client)
    pages=['/','/dashboard','/farms','/notes','/fertilizer','/weather','/analytics','/disease','/growth','/irrigation','/expenses','/market','/calendar','/report','/profile','/logout']
    for page in pages:
        response=client.get(page);assert response.status_code in (200,302),page
        if response.status_code==302:continue
        parser=Scripts();parser.feed(response.get_data(as_text=True))
        for i,script in enumerate(parser.parts):
            if not script.strip():continue
            js=tmp_path/'inline.js';js.write_text(script)
            run=subprocess.run(['node','--check',str(js)],capture_output=True,text=True)
            assert run.returncode==0,(page,i,run.stderr)


def test_stored_farm_payload_stays_text(client):
    register(client)
    payload="x\\');window.XSS=true;//<img src=x onerror=window.XSS=true>"
    client.post('/farms/add',data=dict(farm_name=payload,crop_type='Rice',location='Chattogram',area=1,planting_date='2026-01-01'),headers=H)
    html=client.get('/farms').get_data(as_text=True)
    assert '<img src=x onerror=window.XSS=true>' not in html
    assert 'escPopup(FARM_NAMES[i])' in html
    assert '\\u003cimg' in html


def test_translated_attributes_cannot_break_out():
    import i18n
    html='<span title="Email: x&#34; onmouseover=&#34;alert(1)">safe</span>'
    translated=i18n.translate_html(html)
    assert ' onmouseover="' not in translated
    assert '&quot;' in translated


def test_render_client_ip_requires_explicit_trust(client,monkeypatch):
    monkeypatch.delenv('TRUST_RENDER_PROXY',raising=False)
    with A.app.test_request_context('/',headers={'CF-Connecting-IP':'203.0.113.7'}):assert A.client_ip()!='203.0.113.7'
    monkeypatch.setenv('TRUST_RENDER_PROXY','1')
    with A.app.test_request_context('/',headers={'CF-Connecting-IP':'203.0.113.7'}):assert A.client_ip()=='203.0.113.7'
    with A.app.test_request_context('/',headers={'CF-Connecting-IP':'spoof, bad'}):assert A.client_ip()!='spoof, bad'
