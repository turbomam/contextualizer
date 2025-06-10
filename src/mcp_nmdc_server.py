from mcp.server.fastmcp import FastMCP
import httpx
import logging
from starlette.exceptions import HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("NMDC MCP Server")


@mcp.resource("resource://collections", description="Retrieve the list of NMDC collection names.")
async def get_collections() -> dict:
    url = "https://api.microbiomedata.org/nmdcschema/collection_names"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Upstream request failed: {str(e)}")


# Optionally, add more endpoints:
@mcp.resource("resource://metadata", description="Retrieve metadata about the NMDC schema.")
async def get_metadata() -> dict:
    url = "https://api.microbiomedata.org/nmdcschema/"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


if __name__ == "__main__":
    logger.info("Starting MCP server...")
    mcp.run()
