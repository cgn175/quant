# Quant Bot Development Team Structure

## Team Roles & Responsibilities

### 1. Coordinator (Project Manager)
**Model**: Claude 3.5 Sonnet (high capability)  
**Tools**: `bd`, `grep`, `fs_read`, `execute_bash`, `web_search`  
**Responsibilities**:
- Break down features into issues using `bd`
- Assign tasks to appropriate team members
- Track progress and dependencies
- Coordinate between agents
- Make architectural decisions
- Review final deliverables

**Workflow**:
```bash
# Create issues for new feature
bd create --title "Feature X" --body "..."
# Assign to tech lead for design
# Monitor progress
bd list
```

---

### 2. Tech Lead (Architect)
**Model**: Claude 3.5 Sonnet (high capability)  
**Tools**: `code`, `fs_read`, `grep`, `web_search`, `execute_bash`  
**Responsibilities**:
- Design system architecture
- Review code structure and patterns
- Make technical decisions
- Create implementation plans
- Review complex PRs
- Mentor junior developers

**Workflow**:
```bash
# Analyze codebase
code search_symbols --symbol_name "Strategy"
# Design new component
# Create detailed implementation plan
# Review senior dev's work
```

---

### 3. Senior Developer (Implementation)
**Model**: Claude 3.5 Sonnet (high capability)  
**Tools**: `code`, `fs_read`, `fs_write`, `execute_bash`, `grep`, `glob`  
**Responsibilities**:
- Implement complex features
- Write core business logic
- Integrate multiple systems
- Optimize performance
- Write comprehensive tests
- Document complex code

**Workflow**:
```bash
# Implement feature
code search_symbols --symbol_name "FundingArb"
# Write code
fs_write --command create --path "internal/strategy/new_strategy.go"
# Test
execute_bash "go test ./..."
# Update issue
bd update <id> --status done
```

---

### 4. Junior Developer (Simple Tasks)
**Model**: Claude 3.5 Haiku (fast, cheap)  
**Tools**: `fs_read`, `fs_write`, `execute_bash`, `grep`  
**Responsibilities**:
- Implement simple features
- Fix bugs
- Write unit tests
- Update documentation
- Refactor code
- Add logging/metrics

**Workflow**:
```bash
# Get assigned task
bd show <id>
# Read existing code
fs_read --path "internal/config/config.go"
# Make changes
fs_write --command str_replace
# Test
execute_bash "go test ./internal/config"
# Mark done
bd update <id> --status done
```

---

### 5. Reviewer (Code Quality)
**Model**: Claude 3.5 Sonnet (high capability)  
**Tools**: `code`, `fs_read`, `grep`, `execute_bash`  
**Responsibilities**:
- Review all code changes
- Check for bugs and edge cases
- Verify tests are adequate
- Ensure code style compliance
- Check documentation
- Approve or request changes

**Workflow**:
```bash
# Review changes
git diff main..feature-branch
# Check tests
execute_bash "go test -v ./..."
# Verify code quality
code search_symbols --symbol_name "NewStrategy"
# Approve or request changes
```

---

### 6. QA Engineer (Testing)
**Model**: Claude 3.5 Haiku (fast, cheap)  
**Tools**: `execute_bash`, `fs_read`, `fs_write`, `grep`  
**Responsibilities**:
- Write integration tests
- Run test suites
- Validate bug fixes
- Test edge cases
- Performance testing
- Create test reports

**Workflow**:
```bash
# Run all tests
execute_bash "go test ./... -v"
# Check coverage
execute_bash "go test -cover ./..."
# Run validation scripts
execute_bash "python3 scripts/validate_*.py"
# Report results
```

---

## Task Assignment Matrix

| Task Type | Assigned To | Reviewer | QA |
|-----------|-------------|----------|-----|
| Architecture Design | Tech Lead | Coordinator | - |
| Complex Feature | Senior Dev | Tech Lead | QA |
| Simple Feature | Junior Dev | Senior Dev | QA |
| Bug Fix | Junior Dev | Senior Dev | QA |
| Refactoring | Senior Dev | Tech Lead | QA |
| Tests | Junior Dev | Senior Dev | QA |
| Documentation | Junior Dev | Senior Dev | - |
| Performance Optimization | Senior Dev | Tech Lead | QA |

---

## Workflow Example: New Strategy Implementation

### Phase 1: Planning (Coordinator)
```bash
bd create --title "Implement Market Making Strategy" --body "
Objective: Add market making strategy with inventory management

Tasks:
- [ ] Design architecture (Tech Lead)
- [ ] Implement core logic (Senior Dev)
- [ ] Add config support (Junior Dev)
- [ ] Write tests (Junior Dev)
- [ ] Integration testing (QA)
- [ ] Documentation (Junior Dev)
"
```

### Phase 2: Design (Tech Lead)
- Review existing strategies
- Design interfaces and data structures
- Create implementation plan
- Update issue with design doc

### Phase 3: Implementation (Senior Dev)
- Implement `internal/strategy/market_making/strategy.go`
- Implement core algorithms
- Add metrics and logging
- Write unit tests

### Phase 4: Config & Tests (Junior Dev)
- Add config structs
- Write additional tests
- Update documentation
- Add example configs

### Phase 5: Review (Reviewer)
- Review all code changes
- Check test coverage
- Verify documentation
- Request changes if needed

### Phase 6: QA (QA Engineer)
- Run full test suite
- Test with paper trading
- Validate metrics
- Create test report

### Phase 7: Merge (Coordinator)
- Review all approvals
- Merge to main
- Update project status
- Close issue

---

## Communication Protocol

### Issue Updates
All agents must update issues with:
```bash
bd update <id> --status in_progress  # When starting
# Add comments with progress
bd update <id> --status done  # When complete
```

### Code Comments
```go
// TECH_LEAD: Review this algorithm for efficiency
// SENIOR_DEV: Implemented as per design doc
// REVIEWER: Approved - good test coverage
// QA: Tested - all edge cases pass
```

### Commit Messages
```
feat: Add market making strategy (SENIOR_DEV)
test: Add market making tests (JUNIOR_DEV)
docs: Update strategy documentation (JUNIOR_DEV)
review: Approve market making PR (REVIEWER)
```

---

## Agent Configuration Files

See:
- `.kiro/agents/coordinator.yaml`
- `.kiro/agents/tech-lead.yaml`
- `.kiro/agents/senior-dev.yaml`
- `.kiro/agents/junior-dev.yaml`
- `.kiro/agents/reviewer.yaml`
- `.kiro/agents/qa.yaml`
