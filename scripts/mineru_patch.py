"""
MinerU compatibility patch for transformers >= 4.57.

Handles the class rename from HgNetV2Config to HGNetV2Config and
ensures PP-DocLayoutV2's hgnet_v2 backbone can be loaded correctly.
"""
import sys
import types


def _apply_patch():
    from transformers.models.hgnet_v2 import HGNetV2Config, HGNetV2Backbone

    # Add lowercase aliases for backward compatibility
    import transformers.models.hgnet_v2 as hgnet_v2_mod
    if not hasattr(hgnet_v2_mod, 'HgNetV2Config'):
        hgnet_v2_mod.HgNetV2Config = HGNetV2Config
    if not hasattr(hgnet_v2_mod, 'HgNetV2Backbone'):
        hgnet_v2_mod.HgNetV2Backbone = HGNetV2Backbone

    # Ensure CONFIG_MAPPING has hgnet_v2 entry
    from transformers.models.auto.configuration_auto import CONFIG_MAPPING, MODEL_NAMES_MAPPING
    if 'hgnet_v2' not in CONFIG_MAPPING._mapping:
        CONFIG_MAPPING._mapping['hgnet_v2'] = 'HGNetV2Config'
    if 'hgnet_v2' not in MODEL_NAMES_MAPPING:
        MODEL_NAMES_MAPPING['hgnet_v2'] = 'HGNet-V2'
    CONFIG_MAPPING._modules['hgnet_v2'] = hgnet_v2_mod

    # Register backbone
    from transformers import AutoBackbone
    AutoBackbone.register(HGNetV2Config, HGNetV2Backbone)

    # Patch RTDetrModelOutput for cross-version compatibility
    try:
        from transformers.models.rt_detr.modeling_rt_detr import RTDetrModelOutput
        if not hasattr(RTDetrModelOutput, 'intermediate_predicted_corners'):
            RTDetrModelOutput.intermediate_predicted_corners = property(
                lambda self: None
            )
        if not hasattr(RTDetrModelOutput, 'initial_reference_points'):
            RTDetrModelOutput.initial_reference_points = property(
                lambda self: getattr(self, 'init_reference_points', None)
            )
    except ImportError:
        pass


_apply_patch()
