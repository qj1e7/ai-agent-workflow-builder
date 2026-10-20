from platform_api.builder.models import BlockView, ParamSpec, TemplateView
from platform_api.builder.templates import Template


def template_view(template: Template) -> TemplateView:
    return TemplateView(
        key=template.key,
        name=template.name,
        description=template.description,
        blocks=[
            BlockView(key=b.key, name=b.name, description=b.description, kind=b.kind)
            for b in template.blocks
        ],
        params=[
            ParamSpec(name=p.name, description=p.description, example=p.example)
            for p in template.params
        ],
    )
