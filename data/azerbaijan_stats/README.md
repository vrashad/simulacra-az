# Azerbaijan official stats downloader

This bundle targets the most useful public files for generating synthetic agents for Baku / Azerbaijan.

## Highest-priority files

### Demography
- `001_23en.xls` — population by age groups by economic regions and administrative territorial units
- `001_19en.xls` — population by sex and territory
- `001_21en.xls` — young population (14–29) by territory
- `006_7-8en.xls` — distribution of households by number of members and children

### Labour
- `009_1en.xls` — labour force by territory
- `009_2en.xls` — employment by territory
- `009_3-4en.xls` — unemployment by territory
- `009_5en.xls` — employees by territory
- `009_6en.xls` — wages by territory
- `008_2en.xls` — distribution of employees by economic activity

### Yearbooks / context
- `evtes_2025.pdf` — household survey
- `regions_2025.pdf` — regions of Azerbaijan
- `digital_development_2025.pdf` — digital access / usage
- `WM_2025.pdf` — women and men in Azerbaijan

## Why these files
They map most directly to persona generation fields:
- age band
- sex
- territory / district proxy
- labour force status
- employment sector
- wage / income band proxy
- household composition
- digital activity priors

## Suggested generation pipeline
1. Build marginal distributions from XLS files.
2. Use household survey + wages to create income bands.
3. Use digital development tables to assign online behaviour priors.
4. Ask the LLM to generate biographies only after hard constraints are sampled from the official distributions.
