# podcast-generator: an example briefing

**Briefing:** podcast-generator-intro.pdf
**Voice:** af_heart

## Page 1

This is a short introduction to podcast generator, a tool that turns written scripts into spoken audio on your own computer. It is also an example of what the tool can do. This video was made by podcast generator, from an eleven-page PDF and a narration script. Both are in the examples folder, so you can rebuild it yourself.

## Page 2

Here is the problem it was built for. There are far more research papers than anyone has time to read. A short audio explainer, around seven minutes, is usually enough to decide whether a paper deserves a full read. And listening fits into time that reading can't use, like a commute or a walk. Podcast generator makes that audio locally. There is no API key and no cost per use, and your scripts never leave your machine.

## Page 3

The idea is simple. A script goes in, and audio comes out. The script is a plain markdown file. An open text-to-speech model called Kokoro reads it aloud, in a voice you choose, and an MP3 lands in your outputs folder. There are three ways to run it. You can ask an AI assistant in a chat. You can drop a script into a watched folder. Or you can run one command at the command line. We'll look at the first two.

## Page 4

First, from a chat. Podcast generator includes a connector for AI apps such as Claude Desktop. Once it is set up, you ask for what you want in plain language. In this example, the request is to find a recent technical paper and make a seven-minute podcast about it. The assistant finds a paper, writes the script, queues it, and starts the conversion. A few minutes later it reports that the audio is ready, and where to find it. You should still check the summary against the paper before relying on it. The point is to help you decide what to read, not to replace the reading.

## Page 5

This is what a script looks like. Ordinary paragraphs are spoken. Everything else is silent: headers, lines such as the voice and the link, and the source note in italics at the end. That lets you keep the citation and your own notes in the file without hearing them. One line picks the voice. As an option, a different line turns the script into a conversation between two or more speakers, each with their own voice. And a small lexicon file fixes the pronunciation of acronyms and names.

## Page 6

The second way to run it is the watch folder, which is the easiest way to work from a phone. On Windows, a small app called Podcast Watch sets up a scheduled task that checks an inputs folder. Point that folder at a cloud-synced location. Then you can save a script there from any device. The watch converts whatever is new, moves the script to an archive, and writes the audio to the outputs folder, which syncs back to your phone.

## Page 7

Audio has a limit, though. Podcasts work well for surveying most papers. They work poorly when the argument lives in equations, charts, or tables. The page shown here comes from a briefing on a mathematical paper. Hearing that derivation read aloud is hard to follow. Seeing it while it is explained is much easier. For papers like that, podcast generator can make a narrated briefing: a video that shows each page of a PDF while its narration is read.

## Page 8

A briefing needs two things: a PDF, and a script with page markers. One line in the script names the PDF. Then a line reading page one, page two, and so on, starts the narration for each page. The result is a high-definition video, with subtitles, and a small file recording the timing of each page. The rules are strict on purpose. If a marker is missing, or names a page the PDF doesn't have, the tool stops and tells you what to fix. It will not guess, so you never get a video where the words and the pages disagree.

## Page 9

There are two ways to make one. The easiest is to ask your AI assistant for a narrated briefing video of a paper. The assistant builds the slides as a PDF, writes the narration for each page, and makes the video through the connector. Or you can build the pieces yourself. Export your slides to PDF, from PowerPoint for example. Write the narration, with a page marker before each page's text, or pull it from your speaker notes with one command. Then run the command, or drop the script and the PDF into the watch folder together. The preview option checks the timing first. Either way, there is a one-time setup: install the briefing extra, and make sure the free video tool F F M peg is available.

## Page 10

Before you install, here is what you need. First, Python, version three point ten or later. Python does not come with Claude or Claude Desktop, so install it yourself, or use an installer such as U V, which can fetch Python for you. Second, about two gigabytes of disk space for the speech model and its libraries. It runs on an ordinary processor, so no graphics card is needed. Third, F F M peg, which is usually needed for MP3 output and always needed for narrated briefings. The first run needs an internet connection to download the voice model. After that, everything works offline. The Podcast Watch app is for Windows, though the command line runs on other systems too. And you only need Claude Desktop, or a similar app, if you want the chat connector.

## Page 11

To get started, install podcast generator with pip. Add the optional extras if you want the chat connector or narrated briefings. Then try the examples folder, which holds the script and PDF behind this video, and a sample podcast script. The read me file is a quick start, and the manual covers everything else. The project is open source, at the address shown here.

*Example briefing for podcast-generator. Made with podcast-generator.*
