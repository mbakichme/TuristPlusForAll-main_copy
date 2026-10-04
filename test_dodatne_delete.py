"""Offline guarded deletion acceptance tests."""
import copy
import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import routes
from test_dodatne_edit import Engine, Result

class DeleteEngine(Engine):
    def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        if 'DELETE FROM dodatne' in sql:
            self.calls.append((sql, dict(params)))
            row = self.rows.get(params['stavka_id'])
            for field in ('usluga', 'eur', 'din'):
                assert f'{field} IS NOT DISTINCT FROM :{field}' in sql
            if not row or row['id'] != params['id'] or any(row[f] != params[f] for f in ('usluga', 'eur', 'din')):
                return Result()
            del self.rows[params['stavka_id']]
            return Result([{'stavka_id': params['stavka_id']}])
        if 'SELECT stavka_id FROM dodatne' in sql and ':s AND id = :i' in sql:
            row = self.rows.get(params['s'])
            return Result([row] if row and row['id'] == params['i'] else [])
        return super().execute(query, params)

class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.engine = DeleteEngine()
        with patch.object(routes, 'get_engine', return_value=self.engine), patch.object(routes, 'init_db', lambda e: None):
            self.app = routes.create_app('./dist')
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {'Authorization': 'Bearer ' + routes.create_access_token({'sub': '1'})}

    def delete(self, item=1, original=None, headers=None):
        return self.client.request('DELETE', f'/api/ugovori/33333%2F26/dodatne/{item}',
            headers=self.headers if headers is None else headers,
            json={'original': original or {'usluga': None, 'eur': None, 'din': None}})

    def test_delete_only_selected_row(self):
        self.assertEqual(self.delete().status_code, 200)
        self.assertEqual(set(self.engine.rows), {2, 3})

    def test_conflict_preserves_row(self):
        before = copy.deepcopy(self.engine.rows)
        self.assertEqual(self.delete(3).status_code, 409)
        self.assertEqual(before, self.engine.rows)

    def test_foreign_and_missing_are_404(self):
        for item in (2, 999):
            self.assertEqual(self.delete(item).status_code, 404)
        self.assertEqual(len(self.engine.rows), 3)

    def test_inactive_user_is_forbidden(self):
        self.engine.user.status = 'neaktivan'
        self.assertEqual(self.delete().status_code, 403)

    def test_unauthenticated_is_rejected(self):
        self.assertEqual(self.delete(headers={}).status_code, 401)

    def test_wrapper_required(self):
        response = self.client.request('DELETE', '/api/ugovori/33333/26/dodatne/1', headers=self.headers, json={})
        self.assertEqual(response.status_code, 422)

if __name__ == '__main__':
    unittest.main()
