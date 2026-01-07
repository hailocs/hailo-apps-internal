# LPR Video Results Comparison Report

## Summary
Comparing terminal output results with expected results from `lpr-video-res.txt`

## Detected vs Expected Results

### ✅ Correctly Detected (Exact Match)
| Track ID | Detected | Expected | Status |
|----------|----------|----------|--------|
| 46 | 45790302 | 45790302 | ✅ MATCH |
| 91 | 8236333 | 8236333 | ✅ MATCH |
| 116 | 9357234 | 9357234 | ✅ MATCH |

### ⚠️ Partially Detected (Close but Different)
| Track ID | Detected | Expected | Difference |
|----------|----------|----------|------------|
| 14 | 4528802 | 34528802 | Missing leading "3", different digits |
| 56 | 7495714 | 7493714 | Digit mismatch: "5" vs "3" |
| 95 | 11882266 | 8842266 | Extra "11" prefix |

### ❌ Not Detected (Expected but Missing)
| Track ID | Expected | Notes |
|----------|----------|-------|
| 6 | 13923202 | Not found in terminal output |
| 23 | 43757701 | Detected as invalid ('E' only) |
| 30 | 4874939 | Multiple invalid detections, never cached |
| 69 | check | Detected as invalid ('R' only) - needs manual check |
| 105 | 6697332 | Detected as invalid ('E', 'T' only) |
| 112 | 3040562 | Not found in terminal output |
| 118 | 2603239 | Not found in terminal output |
| 132 | 8535366 | Not found in terminal output |

## Detection Statistics

### From Terminal Output:
- **Total detected tracks**: 6
- **Correct detections**: 3 (50%)
- **Partial detections**: 3 (50%)
- **Missing detections**: 8

### From Expected Results:
- **Total expected tracks**: 14
- **Detection rate**: 6/14 = 42.9%

## Issues Observed

1. **Low Confidence Scores**: All detected plates have very low confidence (0.02-0.03)
2. **Invalid OCR Results**: Many tracks produce invalid single-character or non-license-plate text
3. **Cache Behavior**: Invalid results are not cached (`not_cached track_id=X valid_lp=no`), causing repeated OCR attempts
4. **Missing Tracks**: 8 expected tracks were not detected at all

## Recommendations

1. **Review OCR Model**: Low confidence scores suggest OCR model may need retraining or tuning
2. **Improve Validation**: License plate validation logic may be too strict or too lenient
3. **Track Detection**: Some vehicles may not be properly tracked (tracks 6, 112, 118, 132 missing)
4. **Plate Detection**: Some license plates may not be detected by the plate detection model (tracks 23, 30, 69, 105)

