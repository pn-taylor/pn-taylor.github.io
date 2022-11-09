---
category: Tech
featured_image: '/images/cmd.png'
title: Well That's Pretty Cool
tags: tech, windows, windows 11, windows 10, cmd, admin
excerpt: I've been working in IT for just over fifteen years now. One thing you understand, though, is that you forget more than you learn and that there's always something out there that you never knew about but, once you discover it, you're amazed you didn't know about it before. This happened to me today whilst flicking through TikTok. A lot of the TechToks, as I like to think they're called, are things I've come across before or just seem a touch sketchy. However, despite some initial reservations I'm glad I gave this one a go as it's potentially quite revolutionary for me.
---
I've been working in IT for just over fifteen years now. One thing you understand, though, is that you forget more than you learn and that there's always something out there that you never knew about but, once you discover it, you're amazed you didn't know about it before. This happened to me today whilst flicking through TikTok. A lot of the TechToks, as I like to think they're called, are things I've come across before or just seem a touch sketchy. However, despite some initial reservations I'm glad I gave this one a go as it's potentially quite revolutionary for me.

Working in IT has exposed me to many different operating systems and when it comes to Linux I really quite like how apps and packages are maintained. I mostly use [Ubuntu](https://ubuntu.com/) but I've dabbled with many of the different distrubtions at one time or another. As such, I'm used to running [apt](https://ubuntu.com/server/docs/package-management) on a relatively frequent basis to make sure things are up-to-date. Up until today, keeping all my Windows applications running on their latests versions wasn't so easy; sure most apps will tell you there's an update but wouldn't it be nice if you could do this in a command prompt? Well, wonder no more.

First and foremost, this comes at your own risk. I've ran it and it's worked just fine but, hey, you never know and I'm not responsible for things going sideways. Secondly, click on your start button, type 'cmd' and then make sure to run it as administrator. Once you've got your cmd window up and running type in the following:

```terminal
winget upgrade
```

If you're running this for the first time you'll be asked to accept T&Cs of using the 'msstore' source. Type 'y' then hit enter and you'll eventually be presented with a list of items due for an update.

Name                                           | Id                               |  Version     |  Available   |Source
-----------------------------------------------|----------------------------------|--------------|--------------|------
Plexamp 4.3.0                                  |Plex.Plexamp                      |4.3.0         |4.5.2         |winget
Discord                                        |Discord.Discord                   |1.0.9006      |1.0.9007      |winget
Git                                            |Git.Git                           |2.37.2.2      |2.38.1        |winget
HWiNFO64 Version 7.26                          |REALiX.HWiNFO                     |7.26          |7.30          |winget
OBS Studio                                     |OBSProject.OBSStudio              |28.0.1        |28.1.2        |winget
Plex                                           |Plex.Plex                         |1.55.0        |1.56.2        |winget
Ubisoft Connect                                |Ubisoft.Connect                   |133.0.10702   |135.1.10758   |winget
Microsoft Visual C++ 2013 Redistributable (x64…|Microsoft.VCRedist.2013.x64       |12.0.30501.0  |12.0.40664.0  |winget
VNC Viewer 6.22.515                            |RealVNC.VNCViewer                 |6.22.515.47347|6.22.826.47988|winget
Microsoft Visual C++ 2015-2022 Redistributable…|Microsoft.VCRedist.2015+.x64      |14.31.31103.0 |14.34.31823.3 |winget
NVIDIA PhysX                                   |Nvidia.PhysXLegacy                |9.10.0513     |9.13.0604     |winget
Microsoft Visual C++ 2015-2022 Redistributable…|Microsoft.VCRedist.2015+.x86      |14.31.31103.0 |14.34.31823.3 |winget
Paradox Launcher v2                            |ParadoxInteractive.ParadoxLauncher|2.3.0         |2.4.0         |winget
Microsoft Visual C++ 2013 Redistributable (x86…|Microsoft.VCRedist.2013.x86       |12.0.30501.0  |12.0.40664.0  |winget
Microsoft Windows Desktop Runtime - 6.0.10 (x6…|Microsoft.DotNet.DesktopRuntime.6 |6.0.10        |6.0.11        |winget

Assuming you want to upgrade them all (and that's kind of the point) you'll want to run this command next:

```terminal
winget upgrade --all
```

Then all that happens is that it goes off, downloads the applications newest version and installs it. You'll get a fair few windows pop-up from each applications installation software and it's worth making sure any apps identified as needing an update are closed first but, once the process has finished, you're done and all your apps are up-to-date and all you needed to do was enter two commands; neat huh! (Thanks to @marcustechnology on TikTok)
