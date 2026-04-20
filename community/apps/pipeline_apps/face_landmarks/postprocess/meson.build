project('face_landmarks_postprocess', 'cpp',
  version : '1.0.0',
  default_options : [
    'cpp_std=c++17',
    'warning_level=1',
    'buildtype=release',
  ]
)

postprocess_dep = dependency('hailo-tappas-core', version : '>=3.30.0', required : true)

add_project_arguments('-Wno-psabi', '-Wno-class-memaccess', '-Wno-deprecated-declarations', language : 'cpp')

so_install_dir = '/usr/local/hailo/resources/so'

shared_library('face_landmarks_postprocess',
  'face_landmarks_postprocess.cpp',
  dependencies : [postprocess_dep],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)
