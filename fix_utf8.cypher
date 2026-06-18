// Fix UTF-8 double-encoding corruption in Community nodes
// Corrupted: UTF-8 bytes decoded as Latin-1 (ISO-8859-1)
// Apostrophe (U+2019): E2 80 99 → â + U+0080 + U+0099 (3 chars)
// é: C3 A9 → Ã©   è: C3 A8 → Ã¨   î: C3 AE → Ã®   ç: C3 A7 → Ã§
// ô: C3 B4 → Ã´   ù: C3 B9 → Ã¹   û: C3 BB → Ã»   à: C3 A0 → Ã
// â: C3 A2 → Ã¢   ê: C3 AA → Ãª   ë: C3 AB → Ã«   ï: C3 AF → Ã¯
// «: C2 AB → Â«   »: C2 BB → Â»   nbsp: C2 A0 → Â
MATCH (c:Community)
WHERE c.title        CONTAINS 'Ã' OR c.title        CONTAINS 'â' OR c.title        CONTAINS 'Â'
   OR c.functional_summary CONTAINS 'Ã' OR c.functional_summary CONTAINS 'â' OR c.functional_summary CONTAINS 'Â'
   OR c.technical_summary  CONTAINS 'Ã' OR c.technical_summary  CONTAINS 'â' OR c.technical_summary  CONTAINS 'Â'
WITH c,
  reduce(s = c.title,
    pair IN [
      ['Ã©','é'],['Ã¨','è'],['Ã®','î'],['Ã§','ç'],['Ã´','ô'],
      ['Ã¹','ù'],['Ã»','û'],['Ã ','à'],['Ã¢','â'],['Ãª','ê'],
      ['Ã«','ë'],['Ã¯','ï'],
      ['Â«','«'],['Â»','»'],['Â ','Ã'],
      ['â​™','\'']
    ] | replace(s, pair[0], pair[1])
  ) AS fixed_title,
  reduce(s = c.functional_summary,
    pair IN [
      ['Ã©','é'],['Ã¨','è'],['Ã®','î'],['Ã§','ç'],['Ã´','ô'],
      ['Ã¹','ù'],['Ã»','û'],['Ã ','à'],['Ã¢','â'],['Ãª','ê'],
      ['Ã«','ë'],['Ã¯','ï'],
      ['Â«','«'],['Â»','»'],['Â ','Ã'],
      ['â​™','\'']
    ] | replace(s, pair[0], pair[1])
  ) AS fixed_fs,
  reduce(s = c.technical_summary,
    pair IN [
      ['Ã©','é'],['Ã¨','è'],['Ã®','î'],['Ã§','ç'],['Ã´','ô'],
      ['Ã¹','ù'],['Ã»','û'],['Ã ','à'],['Ã¢','â'],['Ãª','ê'],
      ['Ã«','ë'],['Ã¯','ï'],
      ['Â«','«'],['Â»','»'],['Â ','Ã'],
      ['â​™','\'']
    ] | replace(s, pair[0], pair[1])
  ) AS fixed_ts
SET c.title = fixed_title,
    c.functional_summary = fixed_fs,
    c.technical_summary = fixed_ts
RETURN count(c) AS updated
