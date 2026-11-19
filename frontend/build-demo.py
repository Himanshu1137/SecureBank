"""Builds a single-file, backend-free demo (mock bank in the browser): python build-demo.py -> demo.html"""
import pathlib
d = pathlib.Path(__file__).parent
page = (d / 'index.html').read_text()
css = (d / 'css/style.css').read_text()
api = (d / 'js/api.js').read_text()
app = (d / 'js/app.js').read_text()
page = page.replace('<link rel="stylesheet" href="css/style.css">', f'<style>{css}</style>')
page = page.replace('<meta name="viewport" content="width=device-width, initial-scale=1">',
                    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">')
page = page.replace("window.SB_CONFIG = { mode: 'live', base: '' };", "window.SB_CONFIG = { mode: 'mock', demo: true };")
page = page.replace('<script src="js/api.js"></script>', f'<script>{api}</script>')
page = page.replace('<script src="js/app.js"></script>', f'<script>{app}</script>')
(d / 'demo.html').write_text(page)
print('demo.html', len(page), 'bytes')
