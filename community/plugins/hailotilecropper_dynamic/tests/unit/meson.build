unit_test_sources = {
    'test_no_tiles_dyn'        : 'test_no_tiles.cpp',
    'test_static_tiles_dyn'    : 'test_static_tiles.cpp',
    'test_dynamic_tiles_dyn'   : 'test_dynamic_tiles.cpp',
    'test_combined_tiles_dyn'  : 'test_combined_tiles.cpp',
}

# Link tests against the same plugin sources so we drive the element in-process.
test_inc = include_directories('..', '../..')
test_link_sources = files(
    '../../gsthailobasecropper.cpp',
    '../../gsthailotilecropper_dynamic.cpp',
)

foreach name, src : unit_test_sources
    exe = executable(
        name,
        [src, test_link_sources],
        include_directories : test_inc,
        dependencies        : hailotilecropper_dynamic_deps + [gst_check_dep],
        cpp_args            : ['-DBUILDING_TEST', '-DPACKAGE="hailotilecropper_dynamic"'],
    )
    test(name, exe, suite : 'hailotilecropper_dynamic')
endforeach
