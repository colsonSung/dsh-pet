#!/usr/bin/env python3
"""A small client for the MiniMax media APIs (image + video).

The key comes from the DSH credential store; it is never printed.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HOST = 'https://api.minimaxi.com/v1'


def key():
    t = open(os.path.expanduser('~/.dsh/.credentials.yaml')).read()
    m = re.search(r'^\s*MINIMAX_CN_API_KEY:\s*(\S+)\s*$', t, re.M)
    if not m:
        raise SystemExit('MINIMAX_CN_API_KEY not found')
    return m.group(1).strip('\"')


def post(path, payload, timeout=90):
    req = urllib.request.Request(HOST + path, data=json.dumps(payload).encode(),
        headers={'Authorization': 'Bearer ' + key(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        return {'http_error': e.code, 'body': e.read(400).decode('utf-8', 'replace')}
    except Exception as e:
        return {'error': str(e)[:200]}


def get(path, timeout=60):
    req = urllib.request.Request(HOST + path, headers={'Authorization': 'Bearer ' + key()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        return {'http_error': e.code, 'body': e.read(400).decode('utf-8', 'replace')}
    except Exception as e:
        return {'error': str(e)[:200]}


def download(url, dest):
    with urllib.request.urlopen(url, timeout=180) as r:
        data = r.read()
    with open(dest, 'wb') as f:
        f.write(data)
    return len(data)


def image(prompt, aspect='1:1'):
    """Generate one image; returns the downloaded path."""
    out = post('/image_generation', {'model': 'image-01', 'prompt': prompt, 'n': 1, 'aspect_ratio': aspect})
    urls = (out.get('data') or {}).get('image_urls') or []
    if not urls:
        return None, json.dumps(out)[:300]
    dest = '/tmp/pokesprites/ref_pikachu.png'
    size = download(urls[0], dest)
    return dest, '%d bytes' % size


def video_s2v(subject_image_path, prompt, duration=10, resolution='1080P'):
    """Subject-to-video: keep the same character, give it a new action."""
    with open(subject_image_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        'model': 'S2V-01',
        'prompt': prompt,
        'subject_reference': [{'type': 'character', 'image': 'data:image/png;base64,' + b64}],
        'duration': duration,
        'resolution': resolution,
    }
    return post('/video_generation', payload)


def video_t2v(prompt, duration=6, resolution='1080P'):
    return post('/video_generation', {'model': 'MiniMax-Hailuo-02', 'prompt': prompt,
        'duration': duration, 'resolution': resolution})


def poll(task_id, timeout=900):
    """Wait for a task; returns (status, file_id)."""
    deadline = time.time() + timeout
    last = ''
    while time.time() < deadline:
        q = get('/query/video_generation?task_id=' + task_id)
        status = q.get('status') or ''
        if status != last:
            print('    status: %s' % (status or q.get('base_resp', {}).get('status_msg', '?')))
            last = status
        if status == 'Success':
            return status, q.get('file_id')
        if status in ('Fail', 'Failed'):
            return status, None
        time.sleep(8)
    return 'Timeout', None


def file_url(file_id):
    q = get('/files/retrieve?file_id=' + file_id)
    f = q.get('file') or {}
    return f.get('download_url')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    if cmd == 'image':
        p, info = image(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else '1:1')
        print('  image:', p, info)
    elif cmd == 's2v':
        out = video_s2v(sys.argv[2], sys.argv[3])
        print('  ', json.dumps(out)[:400])
    elif cmd == 't2v':
        out = video_t2v(sys.argv[2])
        print('  ', json.dumps(out)[:400])
    elif cmd == 'poll':
        st, fid = poll(sys.argv[2])
        print('  status:', st, 'file_id:', fid)
        if fid:
            u = file_url(fid)
            print('  url:', (u or '')[:160])
