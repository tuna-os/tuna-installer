pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
viewsdir = join_paths(pkgdatadir, 'tuna_installer/views')

sources = [
  '__init__.py',
  'confirm.py',
  'done.py',
  'progress.py',
  'tour.py',
]

install_data(sources, install_dir: viewsdir)
