import XCTest

/// Runs against the installed DMG app, never an app rebuilt by this Xcode project.
final class ConnectorJourney: XCTestCase {
    private func require(_ condition: Bool, _ message: String = "Required UI state was not reached", file: StaticString = #filePath, line: UInt = #line) throws {
        guard condition else {
            XCTFail(message, file: file, line: line)
            throw NSError(domain: "UmbodUIJourney", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
        }
    }

    @MainActor func testAddEditAndReopenConnector() async throws {
        continueAfterFailure = false
        let env = ProcessInfo.processInfo.environment
        let appPath = try XCTUnwrap(env["UMBOD_UI_APP"])
        let fixture = try XCTUnwrap(env["UMBOD_UI_FIXTURE"])
        let directory = URL(fileURLWithPath: try XCTUnwrap(env["UMBOD_UI_DATA_DIR"]))
        let app = XCUIApplication(url: URL(fileURLWithPath: appPath))
        app.launchArguments = ["--data-dir", directory.path, "--test-credentials"]
        addTeardownBlock { @MainActor in
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.lifetime = .keepAlways
            self.add(screenshot)
            app.terminate()
            try? FileManager.default.removeItem(at: directory)
        }
        app.launch()
        app.activate()
        try require(app.staticTexts["Gateway running"].waitForExistence(timeout: 60), app.staticTexts.allElementsBoundByIndex.map { String(describing: $0.value) }.joined(separator: "\n"))
        app.buttons["Add a connector"].click()
        let name = app.textFields["connector.name"]
        try require(name.waitForExistence(timeout: 5))
        name.click(); name.typeText("UI fixture")
        let command = app.textFields["connector.command"]
        command.click(); command.typeText(appPath + "/Contents/Resources/python/bin/python3")
        let arguments = app.textViews["connector.arguments"]
        arguments.click(); arguments.typeText("-B\n" + fixture)
        app.buttons["connector.save"].click()
        let row = app.buttons["connector.row.UI fixture"]
        try require(row.waitForExistence(timeout: 60), "Saving a new connector must close the editor and show the created connector")
        row.click()
        let toggle = app.descendants(matching: .any).matching(identifier: "tool.allow.echo").firstMatch
        try require(toggle.waitForExistence(timeout: 15))
        toggle.click()
        try await callAgent("stdio")
        app.buttons["Overview"].click()
        app.buttons["Connectors"].click()
        try require(row.waitForExistence(timeout: 5), "Returning to Connectors must show the list")
        row.click()
        app.buttons["Connectors"].click()
        try require(row.waitForExistence(timeout: 5), "Clicking Connectors within a detail must reset to the list")
        row.click()
        app.buttons["Connection settings"].click()
        app.buttons["Edit connection"].click()
        try require(name.waitForExistence(timeout: 5))
        name.click(); name.typeKey("a", modifierFlags: .command); name.typeText("UI fixture edited")
        app.buttons["connector.save"].click()
        try require(app.buttons["connector.save"].waitForNonExistence(timeout: 60))
        try await callAgent("stdio")
        app.terminate()
        app.launch()
        app.activate()
        try require(app.staticTexts["Gateway running"].waitForExistence(timeout: 60), app.staticTexts.allElementsBoundByIndex.map { String(describing: $0.value) }.joined(separator: "\n"))
        app.buttons["Connectors"].click()
        try require(app.buttons["connector.row.UI fixture edited"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["connector.row.UI fixture"].exists, "Editing must not create a duplicate")
    }

    @MainActor private func oracle(_ path: String) async throws -> [String: Any] {
        let env = ProcessInfo.processInfo.environment
        var request = URLRequest(url: try XCTUnwrap(URL(string: try XCTUnwrap(env["UMBOD_UI_FIXTURE_ORIGIN"]) + "/test/" + path)))
        request.httpMethod = path.hasPrefix("agent/") ? "POST" : "GET"
        request.timeoutInterval = 65
        request.setValue("Bearer " + (try XCTUnwrap(env["UMBOD_UI_FIXTURE_CAPABILITY"])), forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200, "Fixture oracle failed for \(path)")
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    @MainActor private func callAgent(_ journey: String) async throws {
        let result = try await oracle("agent/" + journey)
        XCTAssertEqual(result["passed"] as? Bool, true, "The packaged agent must call the UI-enabled tool")
    }

    @MainActor func testBrowserSignInRefreshAndReopen() async throws {
        continueAfterFailure = false
        let env = ProcessInfo.processInfo.environment
        let app = XCUIApplication(url: URL(fileURLWithPath: try XCTUnwrap(env["UMBOD_UI_APP"])))
        app.launchArguments = ["--data-dir", try XCTUnwrap(env["UMBOD_UI_OAUTH_DATA_DIR"]), "--test-credentials"]
        app.launchEnvironment = ["SSL_CERT_FILE": try XCTUnwrap(env["UMBOD_UI_CA"])]
        addTeardownBlock { @MainActor in
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.lifetime = .keepAlways
            self.add(screenshot)
            app.terminate()
        }
        app.launch(); app.activate()
        try require(app.staticTexts["Gateway running"].waitForExistence(timeout: 60))
        app.buttons["Connectors"].click()
        app.buttons["connectors.add"].click()
        app.textFields["connector.name"].click()
        app.textFields["connector.name"].typeText("OAuth fixture")
        app.popUpButtons["connector.transport"].click()
        app.menuItems["Remote · Streamable HTTP"].click()
        app.textFields["connector.url"].click()
        app.textFields["connector.url"].typeText(try XCTUnwrap(env["UMBOD_UI_OAUTH_ENDPOINT"]))
        app.buttons["connector.save"].click()
        let row = app.buttons["connector.row.OAuth fixture"]
        try require(row.waitForExistence(timeout: 60))
        row.click()
        app.buttons["Connection settings"].click()
        app.buttons["Sign in with browser"].click()
        var signedIn = false
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline {
            let state = try await oracle("oauth-ready")
            if state["failed"] as? Bool == true { break }
            if state["ready"] as? Bool == true {
                XCTAssertEqual(state["browser_visits"] as? Int, 1)
                XCTAssertEqual(state["exchanges"] as? Int, 1)
                signedIn = true
                break
            }
            try await Task.sleep(for: .milliseconds(250))
        }
        guard signedIn else { XCTFail("The real browser redirect and PKCE exchange must finish"); return }
        app.activate()
        try require(app.staticTexts["Signed in"].waitForExistence(timeout: 15), "OAuth completion must be visible in Umbod")
        app.buttons["Connect / rediscover"].click()
        try require(app.staticTexts["Connected"].waitForExistence(timeout: 60))
        app.buttons["Done"].click()
        let toggle = app.descendants(matching: .any).matching(identifier: "tool.allow.echo").firstMatch
        try require(toggle.waitForExistence(timeout: 15))
        toggle.click()
        try await callAgent("oauth")
        app.buttons["Connection settings"].click()
        app.buttons["Refresh token"].click()
        try require(app.staticTexts["Token refreshed and transport reconnected."].waitForExistence(timeout: 30))
        try await callAgent("oauth")
        let refreshed = try await oracle("oauth-ready")
        XCTAssertEqual(refreshed["refreshes"] as? Int, 1)
        app.terminate()
        app.launch(); app.activate()
        try require(app.staticTexts["Gateway running"].waitForExistence(timeout: 60))
        app.buttons["Connectors"].click()
        try require(row.waitForExistence(timeout: 15))
        try await callAgent("oauth")
        let restored = try await oracle("oauth-ready")
        XCTAssertEqual(restored["browser_visits"] as? Int, 1, "Stored OAuth credentials must survive relaunch without another browser sign-in")
    }

}
