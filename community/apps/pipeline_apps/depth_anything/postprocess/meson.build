project('depth_anything_postprocess', 'cpp',
    version : '1.0.0',
    default_options : ['warning_level=1', 'buildtype=release', 'cpp_std=c++17',
                       'cpp_args=-Wno-psabi -Wno-class-memaccess -Wno-deprecated-declarations']
)

postprocess_dep = dependency('hailo-tappas-core', version : '>=3.30.0', required : false)
if not postprocess_dep.found()
    postprocess_dep = dependency('hailo_tappas', version : '>=3.30.0', required : false)
endif

if postprocess_dep.found()
    shared_library('depth_anything_postprocess',
        'depth_anything_postprocess.cpp',
        dependencies : postprocess_dep,
        gnu_symbol_visibility : 'default',
        install: false,
    )
else
    error('hailo-tappas-core dependency not found. Install TAPPAS first.')
endif
