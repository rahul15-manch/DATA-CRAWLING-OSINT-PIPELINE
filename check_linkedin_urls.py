import json

d = json.load(open('socially_enriched_leads.json'))
for r in d:
    li = r.get('_social', {}).get('linkedin', {})
    if li.get('source') == 'slug_guess' and li.get('confirmed'):
        print(r['company_name'], '->', li['url'])