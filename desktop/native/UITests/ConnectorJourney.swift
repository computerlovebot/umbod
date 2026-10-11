import XCTest

/// Runs against the installed DMG app, never an app rebuilt by this Xcode project.
final class ConnectorJourney: XCTestCase {
    @MainActor func testAddEditAndReopenConnector() throws {
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
        XCTAssertTrue(app.staticTexts["Gateway running"].waitForExistence(timeout: 60), app.staticTexts.allElementsBoundByIndex.map { String(describing: $0.value) }.joined(separator: "\n"))
        app.buttons["Connectors"].click()
        app.buttons["connectors.add"].click()
        let name = app.textFields["connector.name"]
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.click(); name.typeText("UI fixture")
        let command = app.textFields["connector.command"]
        command.click(); command.typeText(appPath + "/Contents/Resources/python/bin/python3")
        let arguments = app.textViews["connector.arguments"]
        arguments.click(); arguments.typeText("-B\n" + fixture)
        app.buttons["connector.save"].click()
        let row = app.buttons["connector.row.UI fixture"]
        XCTAssertTrue(row.waitForExistence(timeout: 60), "Saving a new connector must close the editor and show the created connector")
        row.click()
        app.buttons["Connection settings"].click()
        app.buttons["Connect / rediscover"].click()
        XCTAssertTrue(app.staticTexts["Connected"].waitForExistence(timeout: 60))
        app.buttons["Done"].click()
        let toggle = app.descendants(matching: .any).matching(identifier: "tool.allow.echo").firstMatch
        XCTAssertTrue(toggle.waitForExistence(timeout: 15))
        toggle.click()
        let agent = Process()
        agent.executableURL = URL(fileURLWithPath: appPath + "/Contents/Resources/python/bin/python3")
        let profile = try String(contentsOfFile: appPath + "/Contents/Resources/umbod-profile", encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        agent.arguments = ["-I", "-B", try XCTUnwrap(env["UMBOD_UI_AGENT"]), appPath + "/Contents/MacOS/umbod-desktop", directory.path, profile]
        try agent.run()
        agent.waitUntilExit()
        XCTAssertEqual(agent.terminationStatus, 0, "An agent must be able to call the tool enabled through the UI")
        app.buttons["Connection settings"].click()
        app.buttons["Edit connection"].click()
        XCTAssertTrue(name.waitForExistence(timeout: 5))
        name.click(); name.typeKey("a", modifierFlags: .command); name.typeText("UI fixture edited")
        app.buttons["connector.save"].click()
        XCTAssertTrue(app.buttons["connector.save"].waitForNonExistence(timeout: 60))
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["Gateway running"].waitForExistence(timeout: 60), app.staticTexts.allElementsBoundByIndex.map { String(describing: $0.value) }.joined(separator: "\n"))
        app.buttons["Connectors"].click()
        XCTAssertTrue(app.buttons["connector.row.UI fixture edited"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.buttons["connector.row.UI fixture"].exists, "Editing must not create a duplicate")
    }
}
