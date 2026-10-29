"""Native catalog UX test; uses a synthetic local gateway, never real keys."""
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from .bookmark import BookmarkFrame
from .diagnostics import wait_until
from .model_picker import ModelPicker
from .settings import Settings, SecretStore


class Gateway(BaseHTTPRequestHandler):
    calls=[]
    def log_message(self,*args):
        pass
    def response(self,data):
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
        later='cursor=' in self.path
        start,end=(200,350) if later else (0,200)
        body={'data':[{'id':f'model-{i:04}','supported_endpoint_types':['openai','openai-response']} for i in range(start,end)],'success':True}
        if not later:
            body['next_cursor']='two'
        self.response(body)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        Gateway.calls.append({'path':self.path,'model':body['model'],'token_limit':body.get('max_tokens',body.get('max_output_tokens')),
                              'auth':'x-api-key' if self.headers.get('x-api-key') else 'bearer'})
        self.response({'output_text':'OK'} if self.path.endswith('/responses') else {'choices':[{'message':{'content':'OK'}}]})


class MemorySecrets(SecretStore):
    def get(self,identity):
        return self._session.get(identity,'')
    def set(self,identity,key):
        self._session[identity]=key
        return True


def run(application,directory):
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),Gateway)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    frame=None
    report={'passed':False,'gateway':'synthetic localhost; 350 models across two pages'}
    try:
        url=f'http://127.0.0.1:{server.server_port}/v1'
        frame=BookmarkFrame(Settings(provider='custom',base_url=url,model='manual-original'),test_mode=True)
        frame.secrets=MemorySecrets()
        frame._auto=False
        frame.preferences('api')
        dialog=frame._dialog
        dialog.key.setText('synthetic-test-key')
        QTest.mouseClick(dialog.validate,Qt.MouseButton.LeftButton)
        wait_until(application,lambda:not dialog._jobs)
        assert len(dialog.models_list)==350 and dialog.model.currentText()=='manual-original'
        assert dialog.model.count()==350
        dialog.grab().save(str(directory/'api-settings.png'))
        report['two_pages_350_models']=True
        def pick():
            picker=QApplication.activeModalWidget()
            assert isinstance(picker,ModelPicker)
            picker.search.setText('0349')
            assert picker.list.count()==1
            picker.list.setCurrentRow(0)
            picker.use_selected()
            assert picker.model_id()=='model-0349'
            picker.search.setText('0123')
            picker.list.item(0).setCheckState(Qt.CheckState.Checked)
            picker.search.setText('manual-original')
            picker.list.item(0).setCheckState(Qt.CheckState.Unchecked)
            assert picker.model_id()=='model-0349'
            picker.search.setText('0349')
            picker.grab().save(str(directory/'model-search.png'))
            picker.accept()
        QTimer.singleShot(120,pick)
        dialog._choose_model()
        assert dialog.model.currentText()=='model-0349'
        dialog._test_model()
        wait_until(application,lambda:not dialog._jobs)
        assert '调用成功' in dialog.message.text(),dialog.message.text()
        assert Gateway.calls[-1]['model']=='model-0349' and Gateway.calls[-1]['token_limit']==64
        report['search_select_and_chat_test']=True
        dialog._save()
        QTest.qWait(150)
        assert frame.settings.model=='model-0349' and frame.bookmark.isVisible() and not frame.isVisible()
        from .catalog import load_enabled
        assert set(load_enabled(frame._connection(),frame.settings.model))=={'model-0123','model-0349'}
        report['only_checked_models_saved']=True
        frame.preferences('api')
        dialog=frame._dialog
        assert set(dialog.enabled_models)=={'model-0123','model-0349'}
        assert len(dialog.models_list)==350 and dialog.model.currentText()=='model-0349'
        report['catalog_cache_and_selected_model_restored']=True
        dialog.model.setEditText('vendor/manual-model')
        dialog.protocol.setCurrentIndex(dialog.protocol.findData('responses'))
        dialog.auth.setCurrentIndex(dialog.auth.findData('x-api-key'))
        dialog._test_model()
        wait_until(application,lambda:not dialog._jobs)
        assert '调用成功' in dialog.message.text(),dialog.message.text()
        call=Gateway.calls[-1]
        assert call=={'path':'/v1/responses','model':'vendor/manual-model','token_limit':64,'auth':'x-api-key'}
        dialog._save()
        QTest.qWait(150)
        assert frame._connection().protocol=='responses' and frame.settings.model=='vendor/manual-model'
        report['manual_id_response_protocol_custom_auth_save']=True
        assert frame.bookmark.isVisible() and not frame.isVisible()
        report['passed']=True
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        if frame:
            frame.close()
            wait_until(application,lambda:not frame.worker_pool.activeThreadCount() and not frame.preferences_pool.activeThreadCount())
            frame.close()
        server.shutdown()
        server.server_close()
        (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return 0 if report['passed'] else 1
