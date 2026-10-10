import time
import tkinter as tk

from PIL import Image

from main import ConverterApp
from converter import CATEGORIES


def test_gui_batch_updates_and_retries(tmp_path):
    root = tk.Tk()
    root.withdraw()
    try:
        app = ConverterApp(root)
        app.category.set(CATEGORIES[2])
        app.category_changed()
        app.target.set('jpg')
        source = tmp_path / '界面测试.png'
        bad = tmp_path / '坏文件.png'
        Image.new('RGB', (32, 24), 'blue').save(source)
        bad.write_bytes(b'corrupt image')
        app.add_paths([source, bad])
        assert len(app.jobs) == 2
        app.directory.set(str(tmp_path / 'results'))
        app.start()
        assert app.running
        deadline = time.monotonic() + 20
        while app.running and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert not app.running
        assert sorted(job['state'] for job in app.jobs.values()) == ['done', 'error']
        assert app.output_paths[0].exists()
        Image.new('RGB', (16, 16), 'green').save(bad)
        app.start()
        while app.running and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert all(job['state'] == 'done' for job in app.jobs.values())
        assert len(app.output_paths) == 2
        assert len(list((tmp_path / 'results').glob('*.jpg'))) == 2
    finally:
        root.destroy()
