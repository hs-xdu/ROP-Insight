"""Factual descriptions for the three shared metrics; no legacy thresholds."""

import math

DESCRIPTION_VERSION = 'common-three-factual-1'
DEFINITIONS = (
    ('vessel_area_density_fov',
     '整体血管覆盖方面',
     '描述有效视野内血管像素的覆盖比例，用于记录本次分割得到的整体血管覆盖程度。',
     '可对照血管Mask与有效视野，核对分割覆盖是否完整。'),
    ('fractal_dimension',
     '血管网络形态复杂程度方面',
     '描述血管分割图的分形复杂程度，用于记录本次血管网络的形态复杂性。',
     '可结合原图与血管Mask核对网络形态；该数值不单独给出临床分期。'),
    ('sliding_window_max_density_gradient',
     '局部血管疏密变化方面',
     '描述滑动窗口计算得到的局部血管密度变化，用于记录血管分布的疏密差异。',
     '可对照局部血管分布与分割连续性，核对疏密变化或分割断裂。'),
)


def describe_features(features):
    by_name={item['key']:item for item in features}
    descriptions=[]
    for key,summary_context,explanation,review_hint in DEFINITIONS:
        feature=by_name[key]
        value=feature.get('value')
        available=(feature.get('status')=='available' and type(value) in (int,float) and math.isfinite(value))
        descriptions.append(dict(key=key,title=feature['title'],status='available' if available else 'unavailable',
            value=value if available else None,unit=feature['unit'],grid=feature['grid'],
            reason=None if available else feature.get('reason') or '未获得有效指标',
            summary_context=summary_context,explanation=explanation,
            review_hint=review_hint if available else '获得有效计算结果后再生成本项形态描述。',
            grade=None,reference_interval=None))
    return dict(rule_version=DESCRIPTION_VERSION,grading_applied=False,items=descriptions)
