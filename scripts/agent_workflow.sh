#!/bin/bash
# Agent Team Workflow Orchestrator

set -e

PROJECT_DIR="/Users/hoangta/projects/quant"
cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Agent Team Workflow"
echo "=========================================="
echo ""

# Function to assign task based on complexity
assign_task() {
    local issue_id=$1
    local complexity=$2
    
    case $complexity in
        "architecture")
            echo -e "${BLUE}→ Assigning to TECH LEAD${NC}"
            echo "Agent: tech-lead"
            echo "Config: .kiro/agents/tech-lead.yaml"
            ;;
        "complex")
            echo -e "${BLUE}→ Assigning to SENIOR DEV${NC}"
            echo "Agent: senior-dev"
            echo "Config: .kiro/agents/senior-dev.yaml"
            ;;
        "simple"|"bug"|"test"|"docs")
            echo -e "${BLUE}→ Assigning to JUNIOR DEV${NC}"
            echo "Agent: junior-dev"
            echo "Config: .kiro/agents/junior-dev.yaml"
            ;;
        *)
            echo -e "${YELLOW}→ Unknown complexity, assigning to COORDINATOR${NC}"
            echo "Agent: coordinator"
            echo "Config: .kiro/agents/coordinator.yaml"
            ;;
    esac
}

# Function to get reviewer
get_reviewer() {
    local assignee=$1
    
    case $assignee in
        "junior-dev")
            echo "senior-dev"
            ;;
        "senior-dev")
            echo "tech-lead"
            ;;
        "tech-lead")
            echo "coordinator"
            ;;
        *)
            echo "reviewer"
            ;;
    esac
}

# Main workflow
case ${1:-help} in
    "create")
        echo -e "${GREEN}Creating new task...${NC}"
        echo ""
        echo "Task type:"
        echo "  1) Architecture design"
        echo "  2) Complex feature"
        echo "  3) Simple feature"
        echo "  4) Bug fix"
        echo "  5) Tests"
        echo "  6) Documentation"
        read -p "Select (1-6): " choice
        
        case $choice in
            1) assign_task "" "architecture" ;;
            2) assign_task "" "complex" ;;
            3) assign_task "" "simple" ;;
            4) assign_task "" "bug" ;;
            5) assign_task "" "test" ;;
            6) assign_task "" "docs" ;;
        esac
        ;;
    
    "assign")
        issue_id=$2
        complexity=$3
        if [ -z "$issue_id" ] || [ -z "$complexity" ]; then
            echo "Usage: $0 assign <issue_id> <complexity>"
            echo "Complexity: architecture|complex|simple|bug|test|docs"
            exit 1
        fi
        assign_task "$issue_id" "$complexity"
        ;;
    
    "review")
        assignee=$2
        if [ -z "$assignee" ]; then
            echo "Usage: $0 review <assignee>"
            exit 1
        fi
        reviewer=$(get_reviewer "$assignee")
        echo -e "${BLUE}→ Assigning review to: $reviewer${NC}"
        echo "Config: .kiro/agents/$reviewer.yaml"
        ;;
    
    "qa")
        echo -e "${BLUE}→ Assigning to QA${NC}"
        echo "Agent: qa"
        echo "Config: .kiro/agents/qa.yaml"
        echo ""
        echo "QA Tasks:"
        echo "  - Run: go test ./... -v"
        echo "  - Run: go test -cover ./..."
        echo "  - Run: python3 scripts/validate_*.py"
        ;;
    
    "status")
        echo "Team Status:"
        echo ""
        bd list
        ;;
    
    "help"|*)
        echo "Usage: $0 <command> [args]"
        echo ""
        echo "Commands:"
        echo "  create              - Create and assign new task"
        echo "  assign <id> <type>  - Assign issue to agent"
        echo "  review <assignee>   - Assign review"
        echo "  qa                  - Assign to QA"
        echo "  status              - Show team status"
        echo ""
        echo "Agent Configs:"
        ls -1 .kiro/agents/*.yaml | sed 's/^/  /'
        ;;
esac
