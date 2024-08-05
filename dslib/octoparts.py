import asyncio

from dslib.fetch import get_browser_page


async def otest():
 pg = await get_browser_page()
 await pg.goto('https://octopart.com/de/search?q=FDP027N08B&currency=USD&specs=0')
 pg.querySelector('')

if __name__ == '__main__':
    asyncio.run(otest())