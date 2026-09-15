"""Unit tests for multi-resume storage, job-targets model, and web API endpoints."""

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from allin.config import (
    get_job_targets,
    normalize_job_targets,
    save_config,
)
from allin.db import get_db, insert_job_if_new
from allin.resume_manager import (
    delete_resume_by_id,
    get_resume_by_id,
    list_resumes,
    save_resume_file,
    update_resume_meta,
)
from allin.web import server


class TestMultiResumeAndTargets(unittest.TestCase):
    def setUp(self):
        self.original_base_dir = server.BASE_DIR
        self.temp_dir = Path(tempfile.mkdtemp())
        server.set_base_dir(self.temp_dir)

        self.config_path = self.temp_dir / 'config.yaml'
        self.resume_dir = self.temp_dir / 'data' / 'resumes'
        self.resume_dir.mkdir(parents=True, exist_ok=True)

        self.legacy_resume = self.temp_dir / 'resume.md'
        self.legacy_resume.write_text('# 张三的简历精通 Python 与 Go 开发', encoding='utf-8')

        self.config = {
            'profile': {
                'resume_path': str(self.legacy_resume.resolve()),
                'resume_output_dir': str(self.resume_dir.resolve()),
                'target_cities': ['北京', '上海'],
                'salary_min': 20,
                'salary_max': 40,
                'extra_highlights': '核心架构师',
                'greeting_preference': '突出并发经验',
            },
            'search': {
                'keywords': ['后端架构', 'Python开发'],
                'cities': ['北京'],
            },
            'job_targets': [],
        }
        save_config(self.config, self.config_path)

    def tearDown(self):
        server.set_base_dir(self.original_base_dir)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _request(self, path: str, method: str = 'GET', json_body: dict | list | None = None):
        if '?' in path:
            path_info, query_string = path.split('?', 1)
        else:
            path_info, query_string = path, ''

        status_headers = {}

        def start_response(status, headers, exc_info=None):
            status_headers['status'] = status
            status_headers['headers'] = dict(headers)

        request_body = json.dumps(json_body).encode('utf-8') if json_body is not None else b''
        environ = {
            'REQUEST_METHOD': method,
            'PATH_INFO': path_info,
            'QUERY_STRING': query_string,
            'SERVER_NAME': '127.0.0.1',
            'SERVER_PORT': '8686',
            'wsgi.version': (1, 0),
            'wsgi.url_scheme': 'http',
            'wsgi.input': io.BytesIO(request_body),
            'wsgi.errors': io.StringIO(),
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
        }
        if json_body is not None:
            environ['CONTENT_LENGTH'] = str(len(request_body))
            environ['CONTENT_TYPE'] = 'application/json'

        response_iter = server.app(environ, start_response)
        try:
            body = b''.join(
                chunk if isinstance(chunk, bytes) else chunk.encode('utf-8')
                for chunk in response_iter
            ).decode('utf-8')
        finally:
            close = getattr(response_iter, 'close', None)
            if close:
                close()
        return status_headers.get('status', '500 Internal Error'), status_headers.get('headers', {}), body

    def test_legacy_resume_auto_indexing(self):
        resumes = list_resumes(self.config, base_dir=self.temp_dir, config_path=self.config_path)
        self.assertEqual(len(resumes), 1)
        self.assertEqual(resumes[0]['id'], 'default')
        self.assertTrue(resumes[0]['is_default'])
        self.assertEqual(resumes[0]['name'], '默认简历')

        meta, content = get_resume_by_id('default', self.config, base_dir=self.temp_dir)
        self.assertIsNotNone(meta)
        self.assertIn('张三的简历', content)

    def test_save_and_manage_multiple_resumes(self):
        list_resumes(self.config, base_dir=self.temp_dir, config_path=self.config_path)

        content2 = '# 李四的AI简历专注于大模型应用与智能体'.encode('utf-8')
        meta2 = save_resume_file(
            content2,
            'ai_resume.md',
            name='AI大模型方向',
            target_direction='LLM/Agent',
            is_default=False,
            config=self.config,
            base_dir=self.temp_dir,
            config_path=self.config_path,
        )
        self.assertEqual(meta2['name'], 'AI大模型方向')
        self.assertFalse(meta2['is_default'])

        resumes = list_resumes(self.config, base_dir=self.temp_dir)
        self.assertEqual(len(resumes), 2)

        updated = update_resume_meta(
            meta2['id'],
            name='AI工程专家',
            is_default=True,
            config=self.config,
            base_dir=self.temp_dir,
            config_path=self.config_path,
        )
        self.assertEqual(updated['name'], 'AI工程专家')
        self.assertTrue(updated['is_default'])
        self.assertEqual(self.config['profile']['resume_path'], meta2['path'])

        ok = delete_resume_by_id('default', self.config, base_dir=self.temp_dir, config_path=self.config_path)
        self.assertTrue(ok)
        resumes_after = list_resumes(self.config, base_dir=self.temp_dir)
        self.assertEqual(len(resumes_after), 1)
        self.assertEqual(resumes_after[0]['id'], meta2['id'])
        self.assertTrue(resumes_after[0]['is_default'])

    def test_job_targets_fallback_and_normalization(self):
        targets = get_job_targets(self.config)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]['id'], 'target_default')
        self.assertEqual(targets[0]['keywords'], ['后端架构', 'Python开发'])
        self.assertEqual(targets[0]['salary_min'], 20)

        custom = [
            {
                'id': 'target_backend',
                'name': '后端开发',
                'enabled': True,
                'resume_id': 'res_1',
                'keywords': ['Golang', 'Python'],
                'cities': ['上海'],
                'salary_min': '25',
                'salary_max': '45',
            },
            {
                'id': 'target_ai',
                'name': 'AI工程师',
                'resume_id': 'res_2',
                'keywords': ['RAG', 'Agent'],
            }
        ]
        norm = normalize_job_targets(custom)
        self.assertEqual(len(norm), 2)
        self.assertEqual(norm[0]['salary_min'], 25)
        self.assertEqual(norm[0]['salary_max'], 45)
        self.assertEqual(norm[1]['salary_min'], 0)
        self.assertTrue(norm[1]['enabled'])

    def test_db_migration_and_job_insert_with_targets(self):
        db_path = self.temp_dir / 'test.db'
        conn = get_db(db_path)
        test_job = {
            'id': 'job_multi_1',
            'title': 'LLM 算法工程师',
            'company': 'OpenAI 合作伙伴',
            'source_platform': 'zhilian',
            'source_job_id': 'ZL123456',
            'source_keyword': 'Agent',
            'target_id': 'target_ai',
            'target_name': 'AI工程师',
            'resume_id': 'res_2',
            'matched_resume_id': 'res_2',
            'matched_resume_name': 'AI工程专家',
        }
        inserted = insert_job_if_new(conn, test_job)
        self.assertTrue(inserted)

        row = conn.execute(
            'SELECT target_id, target_name, resume_id, matched_resume_id, matched_resume_name FROM jobs WHERE id = ?',
            ('job_multi_1',)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['target_id'], 'target_ai')
        self.assertEqual(row['target_name'], 'AI工程师')
        self.assertEqual(row['resume_id'], 'res_2')
        self.assertEqual(row['matched_resume_id'], 'res_2')
        self.assertEqual(row['matched_resume_name'], 'AI工程专家')
        conn.close()

    def test_web_resumes_api_endpoints(self):
        status, _, body = self._request('/api/resumes', 'GET')
        self.assertTrue(status.startswith('200'))
        data = json.loads(body)
        self.assertIn('resumes', data)
        self.assertEqual(len(data['resumes']), 1)
        self.assertEqual(data['resumes'][0]['id'], 'default')

        status, _, body = self._request('/api/resumes/default', 'GET')
        self.assertTrue(status.startswith('200'))
        detail = json.loads(body)
        self.assertIn('content', detail)
        self.assertIn('张三的简历', detail['content'])

        status, _, body = self._request('/api/resumes/default', 'PUT', {'name': '重命名简历', 'target_direction': '后端架构'})
        self.assertTrue(status.startswith('200'))
        updated = json.loads(body)
        self.assertEqual(updated['name'], '重命名简历')
        self.assertEqual(updated['target_direction'], '后端架构')

    def test_web_job_targets_api_endpoints(self):
        status, _, body = self._request('/api/job-targets', 'GET')
        self.assertTrue(status.startswith('200'))
        data = json.loads(body)
        self.assertIn('targets', data)
        self.assertEqual(len(data['targets']), 1)
        self.assertEqual(data['targets'][0]['id'], 'target_default')

        new_targets = [
            {
                'id': 't_backend',
                'name': '后端工程',
                'enabled': True,
                'resume_id': 'default',
                'keywords': ['Go', 'Python'],
                'cities': ['深圳'],
            },
            {
                'id': 't_ai',
                'name': 'AI Agent',
                'enabled': True,
                'resume_id': 'res_ai',
                'keywords': ['LangChain', 'Agent'],
                'cities': ['北京'],
            }
        ]
        status, _, body = self._request('/api/job-targets', 'POST', {'targets': new_targets})
        self.assertTrue(status.startswith('200'))
        saved = json.loads(body)
        self.assertTrue(saved['success'])
        self.assertEqual(len(saved['targets']), 2)

        status, _, body = self._request('/api/job-targets/t_ai', 'PUT', {'name': '大模型应用专家', 'salary_min': 30})
        self.assertTrue(status.startswith('200'))
        updated = json.loads(body)
        self.assertEqual(updated['target']['name'], '大模型应用专家')
        self.assertEqual(updated['target']['salary_min'], 30)

        status, _, body = self._request('/api/job-targets/t_backend', 'DELETE')
        self.assertTrue(status.startswith('200'))

        status, _, body = self._request('/api/job-targets', 'GET')
        self.assertTrue(status.startswith('200'))
        data = json.loads(body)
        self.assertEqual(len(data['targets']), 1)
        self.assertEqual(data['targets'][0]['id'], 't_ai')


if __name__ == '__main__':
    unittest.main()
