install_data(
    'installer.desktop',
    install_dir: join_paths(get_option('datadir'), 'xsessions')
)

install_data(
    'installer.desktop',
    install_dir: join_paths(get_option('datadir'), 'wayland-sessions')
)

install_data(
    'installer.desktop',
    install_dir: join_paths(get_option('datadir'), 'gnome-session', 'sessions')
)

install_data(
    'installer.json',
    install_dir: join_paths(get_option('datadir'), 'gnome-shell', 'modes')
)

install_data(
    'org.bootcinstaller.Installer.policy',
    install_dir: join_paths(get_option('datadir'), 'polkit-1', 'actions')
)

desktop_file = i18n.merge_file(
  input: 'org.bootcinstaller.Installer.desktop.in',
  output: 'org.bootcinstaller.Installer.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: join_paths(get_option('datadir'), 'applications')
)

desktop_utils = find_program('desktop-file-validate', required: false)
if desktop_utils.found()
  test('Validate desktop file', desktop_utils,
    args: [desktop_file]
  )
endif

appstream_file = i18n.merge_file(
  input: 'org.bootcinstaller.Installer.appdata.xml.in',
  output: 'org.bootcinstaller.Installer.appdata.xml',
  po_dir: '../po',
  install: true,
  install_dir: join_paths(get_option('datadir'), 'appdata')
)

appstream_util = find_program('appstream-util', required: false)
if appstream_util.found()
  test('Validate appstream file', appstream_util,
    args: ['validate', appstream_file]
  )
endif

install_data('org.bootcinstaller.Installer.gschema.xml',
  install_dir: join_paths(get_option('datadir'), 'glib-2.0/schemas')
)

compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
  test('Validate schema file', compile_schemas,
    args: ['--strict', '--dry-run', meson.current_source_dir()]
  )
endif

install_data('../recipe.json',
  install_dir: join_paths(get_option('datadir'), 'bootc-installer')
)

install_data('../fisherman/data/images.json',
  install_dir: join_paths(get_option('datadir'), 'bootc-installer')
)

subdir('icons')
