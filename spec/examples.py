  from langywrap.ralph import pipeline, step, gate, every, match, inject                                                                                                               
   
  prompts = "research/ralph/prompts"                                                                                                                                                   
                              
  orient   = step("haiku",   "orient.md",   fail_fast=True)                                                                                                                            
  plan     = step("opus",    "plan.md",     fail_fast=True, tools=["Read", "Write", "Bash"])


                                                                                                                                                                                       
  exec_cond   = switch_best_match(plan.result,                                                                                                                                                               
      lean     = r"sorry.*fill|\.lean|lake build|stage [2-4]",                                                                                                                         
      research = r"web.?research|literature|arXiv|proof.?strateg",  
      mixed = None                                                                                                               
  )                                                                                                                                                                                    

  with exec_cond.mixed:
    execute_result  = step("sonnet",  "execute.md",  timeout=120)  

  with exec_cond.lean:       
    with Loop(retry=5)                                                                                                                    
        execute_result     = step("kimi", "execute.md", timeout=120)
    with if_failed(execute_lean) or not gate("./lean-check.sh --src research/ralph/lean check"):
        execute_result    = step("sonnet", "execute.md", timeout=120)
  with exec_cond.research:
    execute_result = step("kimi", "execute.md", timeout=120,                                                                                                                    
      inject=inject("research_directive.md"))                                                                                                                                                                                                                                                                                                                      


  exec_cond   = switch_best_match(execute_result.result,                                                                                                                                                               
      validate     =  r"unconditional|L3.*rigorous"),                                                                                                                         
      critic = r"sorry.*filled|axiom.*added",                                                                                                                 
  )     

with exec_cond.validate:
    validate = step("gpt-5.2", "validate.md")                                

with exec_cond.critic                                                              
  critic   = step("gpt-5.2", "critic.md")


finalize = step("kimi",    "finalize.md",  tools=["Read", "Write", "Edit", "Glob", "Grep"])                                                                                          

with every(12) or When(execute % r"axiom.*elim" )                                 
    step("sonnet", "adversarial.md")

with every(5)                                                                                              
  step("sonnet", "hygiene.md")         

with every(9)                                                                                                                                                        
  step("sonnet", "lookback.md")                                                                                                                                                                
                                         
gate("just check")                                                                                                                                                                   
gate("lake build", timeout=15, required=False)
                                                         