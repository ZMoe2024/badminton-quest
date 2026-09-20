# Playwright Chromium sandbox profile

`seccomp_profile.json` is copied without modification from Microsoft Playwright v1.63.0:

https://github.com/microsoft/playwright/blob/v1.63.0/utils/docker/seccomp_profile.json

Copyright (c) Microsoft Corporation. Licensed under the Apache License, Version 2.0.
The license is included in `PLAYWRIGHT-LICENSE`.

Container configuration follows https://playwright.dev/python/docs/docker :
run Chromium as an unprivileged user with the supplied seccomp profile.
