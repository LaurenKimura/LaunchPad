# LaunchPad web app

React, TypeScript, Vite, and Tailwind. Operators sign in with the Cognito user pool, see their satellites and recent gaps, and upload one CSV or JSON file.

## Configure

Copy `.env.example` to `.env` and fill in the CDK outputs:

```bash
VITE_USER_POOL_ID=<UserPoolId>
VITE_USER_POOL_CLIENT_ID=<UserPoolClientId>
VITE_API_URL=<UploadApiUrl>
```

`VITE_API_URL` is the API base URL, including the stage path and with no extra path after it. The app sends the Cognito ID token in the `Authorization` header.

## Run

```bash
npm install
npm run dev
```

`npm test` covers sign-in validation, the password rules, the dashboard list, and upload errors. `npm run build` typechecks and builds the static site.

## What the screens do

- **Sign in / Sign up / Sign out.** Email is the username. Sign-up asks for the email confirmation code. Passwords follow the pool rule: 12 characters with upper case, lower case, a digit, and a symbol.
- **Dashboard.** Lists satellites owned by the signed-in operator and the newest anomaly windows.
- **Anomaly.** Opens one gap. A bar chart shows the four likelihoods on a fixed 0–100 scale, and they are not stacked or rescaled to sum to 100. A timeline places the gap against overlapping space-weather events and Earth-shadow intervals. Each cause has its evidence underneath. A side panel shows the latest Kp and recent DONKI events. Timeline rows are buttons, so Tab and Enter work without a pointer.
- **3D globe.** CesiumJS shows the orbit computed with satellite.js from the TLE in effect at the gap. A marker sits at the anomaly start, and a time slider moves the satellite through the window. The South Atlantic Anomaly box from the scoring weights is drawn on the globe. Lighting follows the slider, so the day/night terminator moves with it. The slider is a native range control. No Cesium ion token is required; imagery is the public Esri world imagery service.
- **Upload.** Drag and drop or choose one file. CSV and JSON only, and the file must be under 5 MB. A bad file shows an error and is not sent. A valid file requests a presigned POST and uploads the form fields with the file last.

The estimate disclaimer stays in the layout on every screen: these scores are estimates, not confirmed root causes.
