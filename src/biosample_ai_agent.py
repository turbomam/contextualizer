import os
import logging
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic import BaseModel
import subprocess
import json

# Load environment variables
load_dotenv(verbose=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load CBORG API key from environment variable
api_key = os.getenv("CBORG_API_KEY")

# Debug info
logger.info(f"API key found: {'Yes' if api_key else 'No'}")
if api_key:
    logger.info(f"API key starts with: {api_key[:5]}...")

# Ensure the API key is set
if not api_key:
    raise ValueError("CBORG_API_KEY environment variable is not set.")

# Configure the AI model with CBORG API endpoint
ai_model = OpenAIModel(
    "anthropic/claude-sonnet",
    provider=OpenAIProvider(
        base_url="https://api.cborg.lbl.gov",
        api_key=api_key,
    )
)

# Response models
class BiosampleInfo(BaseModel):
    accession: str
    organism_name: Optional[str] = None
    description_title: Optional[str] = None
    host: Optional[str] = None
    env_broad_scale: Optional[str] = None
    env_local_scale: Optional[str] = None
    env_medium: Optional[str] = None
    package_content: Optional[str] = None
    collection_date: Optional[str] = None
    geo_loc_name: Optional[str] = None
    lat_lon: Optional[str] = None

# Create Biosample Agent
biosample_agent = Agent(
    ai_model,
    system_prompt="""You are a biosample database expert helping users query and understand biological sample data.
    You have access to tools to search MongoDB collections containing biosample metadata.
    Provide clear, informative answers about biosamples, their properties, and environmental contexts.
    When displaying results, format them in a readable way and highlight key information.""",
)

# Helper function to call MongoDB MCP via subprocess (since we're in a Pydantic AI context)
def call_mongodb_mcp(operation: str, **kwargs) -> Any:
    """Call MongoDB MCP operations via Claude Code's MCP interface"""
    # This would need to be implemented based on how MCP is accessible
    # For now, returning None to indicate this needs proper MCP integration
    return None

# Register tools for MongoDB operations
@biosample_agent.tool_plain
def find_biosample_by_accession(accession: str) -> str:
    """
    Find a biosample by its accession number using MongoDB MCP.
    
    :param accession: The biosample accession (e.g., SAMN00000003)
    :return: Biosample information as formatted text
    """
    try:
        logger.info(f"Searching for biosample with accession: {accession}")
        
        # TODO: Integrate with actual MongoDB MCP tools
        # This should call the mcp__MongoDB__find function
        # results = mcp__MongoDB__find(
        #     database="ncbi_metadata",
        #     collection="biosamples_flattened",
        #     filter={"accession": accession}
        # )
        
        # For now, return instruction on how to use MCP directly
        return f"""To find biosample {accession}, you would use:
        
MongoDB MCP Query:
- Database: ncbi_metadata
- Collection: biosamples_flattened  
- Filter: {{"accession": "{accession}"}}

This tool needs to be connected to the MongoDB MCP server to function properly.
Please use the MongoDB MCP tools directly for now."""
        
    except Exception as e:
        logger.error(f"Error finding biosample: {e}")
        return f"Error occurred while searching for biosample: {str(e)}"

@biosample_agent.tool_plain
def search_biosamples_by_organism(organism_name: str, limit: int = 5) -> str:
    """
    Search for biosamples by organism name using MongoDB MCP.
    
    :param organism_name: The organism name to search for
    :param limit: Maximum number of results to return
    :return: List of matching biosamples
    """
    try:
        logger.info(f"Searching for biosamples with organism: {organism_name}")
        
        return f"""To search for biosamples with organism '{organism_name}', use:
        
MongoDB MCP Query:
- Database: ncbi_metadata
- Collection: biosamples_flattened
- Filter: {{"organism_name": {{"$regex": "{organism_name}", "$options": "i"}}}}
- Limit: {limit}

This tool needs MongoDB MCP integration to execute the actual query."""
        
    except Exception as e:
        logger.error(f"Error searching biosamples: {e}")
        return f"Error occurred while searching biosamples: {str(e)}"

@biosample_agent.tool_plain
def search_biosamples_by_environment(env_term: str, limit: int = 5) -> str:
    """
    Search for biosamples by environmental context using MongoDB MCP.
    
    :param env_term: Environmental term to search for
    :param limit: Maximum number of results to return
    :return: List of matching biosamples
    """
    try:
        logger.info(f"Searching for biosamples with environment term: {env_term}")
        
        return f"""To search for biosamples with environment term '{env_term}', use:
        
MongoDB MCP Query:
- Database: ncbi_metadata
- Collection: biosamples_flattened
- Filter: {{"$or": [
    {{"env_broad_scale": {{"$regex": "{env_term}", "$options": "i"}}}},
    {{"env_local_scale": {{"$regex": "{env_term}", "$options": "i"}}}},
    {{"env_medium": {{"$regex": "{env_term}", "$options": "i"}}}}
  ]}}
- Limit: {limit}

This tool needs MongoDB MCP integration to execute the actual query."""
        
    except Exception as e:
        logger.error(f"Error searching biosamples by environment: {e}")
        return f"Error occurred while searching biosamples: {str(e)}"

@biosample_agent.tool_plain
def get_biosample_statistics() -> str:
    """
    Get basic statistics about the biosample collection using MongoDB MCP.
    
    :return: Collection statistics
    """
    try:
        logger.info("Getting biosample collection statistics")
        
        return """To get biosample collection statistics, use these MongoDB MCP queries:

1. Total count:
   - Database: ncbi_metadata
   - Collection: biosamples_flattened
   - Operation: count

2. Human-associated samples:
   - Database: ncbi_metadata  
   - Collection: biosamples_flattened
   - Operation: count
   - Query: {"host": "Homo sapiens"}

3. Package distribution:
   - Database: ncbi_metadata
   - Collection: biosamples_flattened
   - Operation: aggregate
   - Pipeline: [{"$group": {"_id": "$package_content", "count": {"$sum": 1}}}]

This tool needs MongoDB MCP integration to execute the actual queries."""
        
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        return f"Error occurred while getting statistics: {str(e)}"


# Main execution
if __name__ == "__main__":
    print("Biosample AI Agent - MongoDB MCP Integration")
    print("=" * 50)
    print("Note: This agent provides MongoDB query templates.")
    print("For actual data, use the MongoDB MCP tools directly.\n")
    
    # Example queries
    test_queries = [
        "How do I find biosample SAMN00000003?",
        "How do I search for Anaerotruncus colihominis biosamples?", 
        "How do I find human-associated biosamples?",
        "How do I get collection statistics?",
    ]
    
    for query in test_queries:
        print(f"Query: {query}")
        print("-" * 40)
        
        try:
            result = biosample_agent.run_sync(query)
            print(result.data)
        except Exception as e:
            logger.error(f"Error processing query '{query}': {e}")
            print(f"Error: {str(e)}")
        
        print()