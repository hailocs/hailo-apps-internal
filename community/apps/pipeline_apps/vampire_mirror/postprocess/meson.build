project('vampire_overlay', 'cpp',
  version : '1.0.0',
  default_options : [
    'cpp_std=c++17',
    'warning_level=1',
    'buildtype=release',
  ]
)

# hailo-tappas-core provides hailo_objects.hpp / hailo_common.hpp / gst_hailo_meta.hpp
postprocess_dep = dependency('hailo-tappas-core', version : '>=3.30.0', required : false)
if not postprocess_dep.found()
  postprocess_dep = dependency('hailo_tappas', version : '>=3.30.0', required : true)
endif

gst_dep       = dependency('gstreamer-1.0', required : true)
gst_base_dep  = dependency('gstreamer-base-1.0', required : true)
gst_video_dep = dependency('gstreamer-video-1.0', required : true)

opencv_dep = dependency('opencv4', required : false)
if not opencv_dep.found()
  opencv_dep = dependency('opencv', required : true)
endif

add_project_arguments('-Wno-psabi', '-Wno-class-memaccess', '-Wno-deprecated-declarations', language : 'cpp')

# Install the GStreamer element into the system GStreamer plugin directory so
# gst-inspect/the pipeline can discover it (same location as the tappas plugins).
gst_plugins_dir = '/usr/lib/gstreamer-1.0'
gst_plugins_dir_result = run_command('pkg-config', '--variable=pluginsdir', 'gstreamer-1.0', check : false)
if gst_plugins_dir_result.returncode() == 0 and gst_plugins_dir_result.stdout().strip() != ''
  gst_plugins_dir = gst_plugins_dir_result.stdout().strip()
endif
message('GStreamer plugin install dir: @0@'.format(gst_plugins_dir))

shared_library('gsthailovampire_overlay',
  ['gsthailovampire_overlay.cpp',
   'vampire_draw.cpp'],
  dependencies : [postprocess_dep, gst_dep, gst_base_dep, gst_video_dep, opencv_dep],
  cpp_args : ['-DPACKAGE="hailovampire_overlay"'],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : gst_plugins_dir,
)
