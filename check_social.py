import json

d = json.load(open('socially_enriched_leads.json'))
found_on_site = sum(1 for r in d if r['_social'].get('linkedin', {}).get('source') == 'found_on_site')
guessed = sum(1 for r in d if r['_social'].get('linkedin', {}).get('source') == 'slug_guess')
confirmed_guesses = sum(1 for r in d if r['_social'].get('linkedin', {}).get('source') == 'slug_guess' and r['_social']['linkedin'].get('confirmed'))
print('LinkedIn actually found on their own website:', found_on_site)
print('LinkedIn guessed from company name:', guessed)
print('  of those guesses, confirmed live (rare, LinkedIn blocks bots):', confirmed_guesses)