# Resume Mustache System

This repo separates **content** (Markdown) from **presentation** (HTML templates).

## Files

- `resume.md` — the **content** (edit this)
- `templates/resume_base.mustache.html` — original-style, two-column theme
- `templates/resume_minimal.mustache.html` — clean single-column theme
- `resume_render.py` — parses `resume.md` and renders a template
- `mustache.py` — tiny dependency-free Mustache renderer
- `Steven_A_Thompson_Resume.html` — the generated resume (HTML output)

## Render

From this folder:

```bash
python resume_render.py --content resume.md --template templates/resume_base.mustache.html --output Steven_A_Thompson_Resume.html
```

Optional: dump the parsed data structure as JSON (useful when making new templates):

```bash
python resume_render.py --content resume.md --template templates/resume_base.mustache.html --output resume_generated.html --data-out resume_data.json
```

## Make new styles

Create a new file in `templates/` and use Mustache tags like:

- `{{person.full_name}}`
- `{{#skills}} ... {{/skills}}`
- `{{#experience}} ... {{/experience}}`
- `{{#bullets}} ... {{/bullets}}`

To conditionally render links:

```html
{{#href}}<a href="{{href}}">{{value}}</a>{{/href}}{{^href}}{{value}}{{/href}}
```
