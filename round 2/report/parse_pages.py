# Compute body page numbers for the TOC from the pass-1 PDF (monotonic cursor).
import subprocess, json, sys
PDF=sys.argv[1] if len(sys.argv)>1 else '/tmp/rep/VGuard-Sentinel-Detailed-Report.pdf'
OUT='/home/theperson/Vajra/MyProjects/VGuard26/docs/report/pagemap.json'
txt=subprocess.run(['pdftotext',PDF,'-'],capture_output=True,text=True).stdout
pages=txt.split('\f')
# (toc_title, distinctive search key found in the BODY heading line)
ENTRIES=[
 ("1. Introduction","1. Introduction"),
 ("2. Problem Context and Motivation","2. Problem Context"),
 ("2.1 India's power-reliability gap","2.1 India"),
 ("2.2 The battery as the silent point of failure","2.2 The battery"),
 ("2.3 Why degradation is predictable, and why today's products miss it","2.3 Why degradation"),
 ("2.4 The cost of the status quo","2.4 The cost"),
 ("3. Proposed Solution: V-Guard Sentinel","3. Proposed Solution"),
 ("4. System Architecture","4. System Architecture"),
 ("5. Hardware Design of the AI Core","5. Hardware Design"),
 ("5.1 Compute","5.1 Compute"),
 ("5.2 Isolated sensing front-end","5.2 Isolated"),
 ("5.3 Actuation, power and mechanical","5.3 Actuation"),
 ("5.4 Cost: the incremental-versus-standalone reality","5.4 Cost"),
 ("6. Engine 1: Predictive Battery Health and Remaining Useful Life","6. Engine 1"),
 ("6.1 Estimation stack","6.1 Estimation"),
 ("6.2 Data strategy and the lead-acid gap","6.2 Data strategy"),
 ("6.3 On-device feasibility","6.3 On-device"),
 ("6.4 Honest lead-time framing","6.4 Honest"),
 ("7. Engine 2: Habit-Learning Autopilot and Load Prioritisation","7. Engine 2"),
 ("8. Engine 3: Energy Coach and Grid Shield","8. Engine 3"),
 ("9. Engine 4: Federated Fleet Intelligence","9. Engine 4"),
 ("10. Key Parameters and Performance Targets","10. Key Parameters"),
 ("11. Prototype and Validation Plan","11. Prototype"),
 ("12. Standards, Safety and Compliance","12. Standards"),
 ("13. Feasibility and Manufacturing","13. Feasibility"),
 ("14. Business Value and Market Opportunity","14. Business Value"),
 ("15. Sustainability and Social Impact","15. Sustainability"),
 ("16. Competitive Differentiation","16. Competitive"),
 ("17. Risks and Mitigations","17. Risks"),
 ("18. Roadmap and Vision","18. Roadmap"),
 ("References","References"),
]
# body starts at the SECOND occurrence of "1. Introduction" (first is in the TOC)
occ=[i for i,pg in enumerate(pages) if "1. Introduction" in pg]
cursor = occ[1] if len(occ)>=2 else (occ[0] if occ else 0)
pagemap={}
for title,key in ENTRIES:
    found=None
    for i in range(cursor,len(pages)):
        if key in pages[i]:
            found=i; break
    if found is None:  # fallback: search whole doc after TOC
        for i in range(cursor,len(pages)):
            if key.split()[0] in pages[i]:
                found=i; break
    if found is not None:
        pagemap[title]=found+1  # 1-based
        cursor=found
    else:
        pagemap[title]=""
json.dump(pagemap,open(OUT,'w'),indent=1)
print("pagemap written:",OUT)
print(json.dumps(pagemap,indent=1))
