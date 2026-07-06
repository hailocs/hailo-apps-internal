project('hailotilecropper_dynamic', 'cpp',
  version : '1.0.0',
  default_options : [
    'cpp_std=c++17',
    'warning_level=1',
    'buildtype=release',
  ]
)

# hailo-tappas-core provides hailo_objects.hpp / gst_hailo_meta.hpp and the
# tiling metadata headers. This element bundles its own GstHailoBaseCropperDyn
# base class, so it does NOT need the system-wide TAPPAS base cropper.
postprocess_dep = dependency('hailo-apps-core', version : '>=3.30.0', required : false)
if not postprocess_dep.found()
  postprocess_dep = dependency('hailo-tappas-core', version : '>=3.30.0', required : false)
endif
if not postprocess_dep.found()
  postprocess_dep = dependency('hailo_tappas', version : '>=3.30.0', required : true)
endif

gst_dep       = dependency('gstreamer-1.0', required : true)
gst_base_dep  = dependency('gstreamer-base-1.0', required : true)
gst_video_dep = dependency('gstreamer-video-1.0', required : true)

opencv_dep = dependency('opencv4', required : false)
if not opencv_dep.found()
  opencv_dep = dependency('opencv', required : false)
endif

add_project_arguments('-Wno-psabi', '-Wno-class-memaccess', '-Wno-deprecated-declarations', language : 'cpp')

# --- TAPPAS version → -DHAILO_TAPPAS_VER (major*100+minor) -------------------
tappas_ver_int = 0
pkg_name = 'hailo-apps-core'
pkg_version_result = run_command('pkg-config', '--modversion', pkg_name, check : false)
if pkg_version_result.returncode() != 0
  pkg_name = 'hailo-tappas-core'
  pkg_version_result = run_command('pkg-config', '--modversion', pkg_name, check : false)
endif
if pkg_version_result.returncode() != 0
  pkg_name = 'hailo_tappas'
  pkg_version_result = run_command('pkg-config', '--modversion', pkg_name, check : false)
endif
if pkg_version_result.returncode() == 0
  version_parts = pkg_version_result.stdout().strip().split('.')
  if version_parts.length() >= 2
    tappas_ver_int = version_parts[0].to_int() * 100 + version_parts[1].to_int()
  endif
endif
message('TAPPAS version int: @0@'.format(tappas_ver_int))

hailotilecropper_dynamic_deps = [postprocess_dep, gst_dep, gst_base_dep, gst_video_dep]
if opencv_dep.found()
  hailotilecropper_dynamic_deps += opencv_dep
endif

# Install into the system GStreamer plugin dir so gst-inspect / pipelines discover it.
gst_plugins_dir = '/usr/lib/gstreamer-1.0'
gst_plugins_dir_result = run_command('pkg-config', '--variable=pluginsdir', 'gstreamer-1.0', check : false)
if gst_plugins_dir_result.returncode() == 0 and gst_plugins_dir_result.stdout().strip() != ''
  gst_plugins_dir = gst_plugins_dir_result.stdout().strip()
endif
message('GStreamer plugin install dir: @0@'.format(gst_plugins_dir))

shared_library('gsthailotilecropper_dynamic',
  ['gsthailobasecropper.cpp',
   'gsthailotilecropper_dynamic.cpp'],
  include_directories : include_directories('.'),
  dependencies : hailotilecropper_dynamic_deps,
  cpp_args : ['-DPACKAGE="hailotilecropper_dynamic"', '-DHAILO_TAPPAS_VER=' + tappas_ver_int.to_string()],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : gst_plugins_dir,
)

# Unit tests (gstreamer-check). Built only when the check framework is present;
# run with `meson test -C build`. tests/unit/meson.build links the plugin
# sources directly and expects `hailotilecropper_dynamic_deps` + `gst_check_dep`.
gst_check_dep = dependency('gstreamer-check-1.0', required : false)
if gst_check_dep.found()
  subdir('tests/unit')
else
  message('gstreamer-check-1.0 not found — skipping hailotilecropper_dynamic unit tests')
endif
