# Automate a Department Back Office Task with Graphs

## *Mainsail AI Launch Labs*

---

## **Reference Material**

Before starting, review the [Prod Evals Playbook](https://github.com/Gauntlet-HQ/prod-evals-cookbook) and the Graph Systems lesson materials on the Portal.

## **Overview**

In this assignment, you will design and implement a graph-based automation that fully completes a real “back office” workflow for a department. 

Your goal is to practice turning a messy, multi-step operational process into a reliable graph with clear state, tool calls, and guardrails. This is an applied systems assignment focused on graph design decisions, reliability, and evaluation, not UI or polish.

### **Due Date**  Monday, February 2nd at 11:59 PM CT.

#### Task Requirements

Pick 1 back office task from any department, such as:

1. **HR**: onboarding checklist automation, policy Q\&A \+ ticket creation, interview scheduling coordination  
2. **Operations**: vendor intake, purchase approval routing, weekly KPI report generation  
3. **Engineering**: triage \+ routing for bug reports, incident follow-ups, changelog drafting \+ PR creation  
4. **Finance**: invoice intake and categorization, monthly close checklist assistant

Your task must meet these criteria:

* It is multi-step (at least 5 distinct steps)  
* It requires at least 2 tools (for example: email, Slack, Google Drive, calendar, Jira/Linear, GitHub, database, HTTP APIs)  
* It ends in a clear “done” output (a created ticket, a completed doc, a posted summary, an updated record, etc.)

#### Graph Implementation Requirements

You must implement a working graph that includes:

1. Defined state (what the system tracks between steps)  
2. Nodes that perform distinct steps (classification, retrieval, decision, execution, verification, etc.)  
3. At least 1 branching decision (if/else or router node)  
4. At least 1 loop (retry, clarification, or iterative improvement)  
5. A final verification step (the graph checks the output before marking complete)

#### Framework Options

You may use either:

* n8n (any nodes you want), or  
* LangGraph (build the graph from scratch)

No client or UI is required. The system can run locally, via scripts, or as an API.  ￼

#### Eval Requirement (Golden Set Minimum)

You must implement at least one golden set from the Eval Playbook:

* Create a set of 10 to 20 representative inputs for your workflow (your “golden set”).  
* For each input, define the expected outcome in a way that can be checked (pass/fail or scored rubric).  
* Run the golden set through your graph and report results.

Your eval must measure graph reliability, not just whether the final LLM output sounds good. 

Examples of what to evaluate:

* Correct routing decisions (did it choose the right path?)  
* Correct tool usage (did it call the right tool with the right arguments?)  
* Task completion (did it end with the required artifact?)  
* Hallucination resistance (did it avoid inventing fields, links, or statuses?)

#### Submission Requirements

### Video Walkthrough

Submit a **3 to 5 minute video** explaining:

* How your automation is structured

* Your eval strategy and golden set

* Your graph state and branching

* The eval you chose and why

Grading Criteria

* Clear graph design and state management

* Correct implementation of branching and looping

* Realistic automation scope (end-to-end completion)

* Proper golden set implementation and meaningful checks

* Thoughtful reasoning about tradeoffs

* Code clarity and organization

---

Ready to face the Gauntlet?

*Gauntlet AI \- Where only the strongest AI-first engineers emerge.*
